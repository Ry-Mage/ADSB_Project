import requests
import psycopg
import pandas as pd
import numpy as np
import json
from io import StringIO
from psycopg import sql
from pydantic import BaseModel
from sqlalchemy import create_engine
import time
import plotly.graph_objects as go
import colorsys
from h3 import latlng_to_cell, cell_to_boundary
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
from cartopy import geodesic
import cartopy.feature as cfeature


pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', 150)





# TODO
# Incorporate weather data in another table, perhaps use that for something?
# Function to find a flight from plane model, sqwuak code, or (? any other interesting things. Roll, climb, velocity?) and recreate its flight path
#  add function to map multiple paths on one map?
# 
# 

# Dictionary to map python data types to SQL data types for adding/creating tables
pyDType_to_sqlDType = {
    'object' : 'text',
    'string' : 'text',
    'int64' : 'int8',
    'float64' : 'float8',
    'str[]' : 'text[]',
    'dict' : 'text'
}
    
# Queries the airplanes live API for given lat,long,radius circle. Includes some handling of problematic variables like unpacking variables the API returns as JSON or SQL keywords. Adds a column for the time when the query was made as unix time format
def retrieve_area(lat, long, radius):
    r = requests.get(f'https://api.airplanes.live/v2/point/{lat}/{long}/{radius}')
    rJSONStr = json.dumps(r.json())
    rJSONStr = rJSONStr[rJSONStr.find('['):rJSONStr.rfind(']')]
    rJSONStr = rJSONStr + ']'
    rJsonStrIO = StringIO(rJSONStr)
    rdf = pd.read_json(rJsonStrIO, orient = 'records')
    if 'desc' in rdf.columns:
        rdf.rename(columns = {'desc' : 'Description'}, inplace = True)
    rdf.insert(column ='time', value = time.time(), loc = len(rdf.columns))
    if 'acas_ra' in rdf.columns:
        rdf['acas_ra'] = rdf['acas_ra'].apply(lambda x: json.dumps(x) if isinstance(x, dict) else x)
    return rdf

# Takes a dataframe of ADSB data and adds to PostgreSQL db. If the dataframe has columns that aren't already in the SQL table they are added
def add_df_db(df):
    with psycopg.connect("dbname = **** user = **** password = ****") as conn:
        engine = create_engine('postgresql+psycopg://postgres:****@localhost:****/***')
        with conn.cursor() as cur:
            try:
                df.to_sql(name = 'yer', con = engine, if_exists = 'append')
                print('DATAFRAME ADDED TO DATABASE')
            except:
                sqlQ = "SELECT column_name FROM information_schema.columns where table_name = 'yer'"
                currDBdf = pd.read_sql(sql = sqlQ, con = engine)
                for col in df.columns:
                    dt = pyDType_to_sqlDType[df[col].dtype.name]
                    if not col in currDBdf['column_name'].values:
                        print(f'FOUND COLUMN NOT IN TABLE {col}, ADDING')
                        query = sql.SQL('ALTER TABLE {table} ADD COLUMN {column} {datatype}').format(table = sql.Identifier('yer'), column = sql.Identifier(col), datatype = sql.SQL(dt))
                        print(f'QUERY: {query}')
                        cur.execute(query)
                        conn.commit()
                print('FINISHED QUERY')
                df.to_sql(name = 'yer', con = engine, if_exists = 'append')

# Queries the given lat,lon,radius/area circle and adds planes within to Postgre db
def query_area_and_add(lat, long, area):
    yer = retrieve_area(lat, long, area)
    add_df_db(yer)

# Helper function for recreate_path() to vary color of plotted points based on the planes alitutde at time of collection
def alt_color_picker(row):
    alt = str(row['alt_baro'])
    if 'ground' in alt:
        rgb = 'rgb(255,255,255)'
        return rgb
    else: 
        alt = int(alt)
        rgb = (alt/100000 * 255, 25, 50)
        return 'rgb' + str(rgb)
    
# Helper function for recreate_path() to vary size of plotted points based on the planes velocity at time of collection
def velocity_size_picker(row):
    if np.isnan(row['gs']):
        return 3
    return row['gs'] / 50
    

# Queries the Postgre db for given flight and plots/visualizes its flight path 
def recreate_path(flight, table):
    query = sql.SQL("SELECT * FROM {table} WHERE {table}.flight = %s").format(table = sql.Identifier(table))
    with psycopg.connect("dbname = **** user = **** password = ****") as conn:
        with conn.cursor() as cur:
            #Trim trailing spaces from flight
            cur.execute(sql.SQL('UPDATE {table} SET flight = rtrim(flight)').format(table = sql.Identifier(table)))
            cur.execute(query, (flight,))
            colNames = [desc[0] for desc in cur.description]
            flightdf = pd.DataFrame(columns = colNames)
            intermediatedf = pd.DataFrame(cur.fetchall())
            x = 0
            for col in colNames:
                flightdf[col] = intermediatedf[x]
                x += 1
            flightdf['color'] = flightdf.apply(alt_color_picker, axis = 1)
            flightdf['size'] = flightdf.apply(velocity_size_picker, axis = 1)
            flightdf = flightdf.set_index('time').sort_index(axis = 0).reset_index()
            
    fig = go.Figure(go.Scattergeo(
                    lat = flightdf['lat'],
                    lon = flightdf['lon'],
                    mode = 'lines+markers',
                    marker = dict(
                        size = flightdf['size'],
                        color = flightdf['color'],
                    )
    ))
    fig.update_layout(
        title = f'Flight: {flight} path reconstruction',
        geo = dict (scope = 'usa')
    )
    fig.show()

# Helper function to return H3 cells for GIS points
def h3_helper(row):
    lat = row[1]
    lng = row[0]
    res = row['zoom']
    return latlng_to_cell(lat = lat, lng = lng, res = res)

# Helper function for generate_h3_cells() to take the H3 cells from h3_helper() and convert them to WKT formatted polygons
def h3WKT_helper(h3):
    polyBoundsTup = cell_to_boundary(h3)
    polyBounds = ''
    for tup in polyBoundsTup:
        polyLat, polyLon = str(tup).rstrip('()').split(',')
        polyLonLat = polyLon + polyLat
        polyLonLat = polyLonLat.replace('(', ' ').strip()
        polyBounds = polyBounds + polyLonLat + ', '
    polyBounds = polyBounds.rstrip(', ')
    return f'POLYGON(({polyBounds}))'


# Query a PostgreSQL db and write to a file WKT polygons of H3 cells at the specified zoom level
def generate_h3_cells(lonField, latField, table, zoom):
    query = sql.SQL("SELECT {lon},{lat} FROM {table}").format(lon = sql.Identifier(lonField), lat = sql.Identifier(latField), table = sql.Identifier(table))
    with psycopg.connect("dbname = **** user = **** password = ****") as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            lonLatdf = pd.DataFrame(cur.fetchall())
            lonLatdf['zoom'] = zoom
            lonLatdf['h3Cell'] = lonLatdf.apply(h3_helper, axis = 1)
        h3Counts = lonLatdf['h3Cell'].value_counts()
    with open(f'h3s_z{zoom}.csv', 'w') as f:
        f.write('wkt|num_observations\n')
        for poly in h3Counts.index:
            f.write(f'{h3WKT_helper(poly)}|{h3Counts[poly]}\n')
        
# Function to query airplanes live API for given lat,long,radius circles, remove duplicate ADSB entries/data, and add to PostgreSQL db. Useful as using circles to cover geographic areas results in some overlap and potential duplicates
def multi_point_query_dedup_add(points):
    hyer = pd.DataFrame()
    for point in points:
        lat, lon, rad = str(point).replace('(', '').replace(')', '').replace(' ', '').replace("'", "").split(',')
        idf = retrieve_area(lat, lon, rad)
        hyer = pd.concat([hyer, idf]).drop_duplicates(subset = ['flight'])
        time.sleep(0.55)
    add_df_db(hyer)
    
# Helper function for plot_points() to print the lat,lon of the mouse when the map is clicked
def get_point(event):
    if event.inaxes:
        x, y = event.xdata, event.ydata
        lon, lat = ccrs.PlateCarree().transform_point(x, y, ccrs.PlateCarree())
        print(f'Lat: {lat}, Long: {lon}')

# Helper function to visualize points you'd like to query data from
def plot_points(points):
    data = [(float(lat), float(lon), float(rad)) for lat, lon, rad in points]
    latMin, latMax, lonMin, lonMax = min(data, key = lambda t: t[0])[0], max(data, key = lambda t: t[0])[0], min(data, key = lambda t: t[1])[1], max(data, key = lambda t: t[1])[1]
    fig = plt.figure(figsize = (15, 10))
    ax = plt.axes(projection = ccrs.PlateCarree())
    ax.set_extent([lonMin - 5, lonMax + 5, latMin - 5, latMax + 5], crs = ccrs.PlateCarree())
    ax.add_feature(cfeature.LAND)
    ax.add_feature(cfeature.OCEAN)
    ax.add_feature(cfeature.COASTLINE)
    ax.add_feature(cfeature.BORDERS, linestyle = ':')
    for lat, lon, rad in data:
        radMeters = rad * 1852
        geo = geodesic.Geodesic()
        geoCirc = geo.circle(lon = lon, lat = lat, radius = radMeters, n_samples = 100)
        ax.plot([p[0] for p in geoCirc], [p[1] for p in geoCirc], transform = ccrs.PlateCarree(), color = 'red')
    fig.canvas.mpl_connect('button_press_event', get_point)
    plt.title(points)
    plt.show()

# Recreates given flights paths from tail/registration number
def multi_path_recreate(flights, table):
    for flight in flights:
        recreate_path(flight, table)

#Points that cover most of the US: 
usPoints = [('47','-121', '250'),('40', '-120', '250'), ('34', '-115.5', '250'), ('45.7', '-112.4', '250'), ('39.1', '-110.2', '250'), ('32.5', '-106.4', '250'), ('38.7', '-100', '250'), ('31.57', '-98.4', '250'), ('45', '-103.3', '250'), ('45.4', '-94', '250'), ('38', '-92.28', '250'), ('31.8', '-89.8', '250'), ('28.24', '-81.8', '250'), ('36.1', '-82.22', '250'), ('42.8', '-84.42', '250'), ('41.3', '-75', '250'), ('45.55', '-68.42', '173'), ('35.98', '-76.1', '112'), ('37', '-105.25', '50'), ('30.5', '-75.8', '250'), ('35.87', '-87.58', '30'), ('38.67', '-86.8', '30'), ('42.08', '-90.2', '30'), ('40.8', '-105.1', '30'), ('41.75', '-114.82', '30'), ('43.03', '-127.62', '175'), ('33.75', '-123.82', '210'), ('24.8', '-88.82', '250'), ('25.9', '-96.1', '250'), ('38', '-128.4', '200'), ('26', '-104.9', '250'), ('28.1', '-120.13', '250'), ('27', '-114', '250'), ('32.18', '-84.68', '40'), ('51', '-64', '250'), ('47.8', '-75.6', '250'), ('49.45', '-86.1', '250'), ('52.1', '-98', '250'), ('52.1', '-107', '250'), ('53', '-116.28', '250'), ('53.96', '-125.75', '250'), ('49', '-131.32', '250'), ('44.23', '-61.4', '190')]

# Continuously queries the airplanes live API for the specfied circles of lat,lon,radius every timeToWait seconds, default every 60 seconds
def continuous_multi_query(points, timeToWait = 60):
    while True:
        print('Querying Airplanes.live API:')
        multi_point_query_dedup_add(points)
        #query_area_and_add('40', '-105', '250')
        print(f'Finished Query and Database Add, waiting {timeToWait}s to requery')
        time.sleep(timeToWait)
    
# Continuously queries the airplanes live API for the specfied circle of lat,lon,radius every timeToWait seconds, default every 60 seconds
def continuous_single_query(point, timeToWait = 60):
    while True:
        print('Querying Airplanes.live API:')
        query_area_and_add(point)
        print(f'Finished Query and Database Add, waiting {timeToWait}s to requery')
        time.sleep(timeToWait)

#continuous_multi_query(usPoints, 60)