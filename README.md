# ADSB_Project
A personal project to query aircraft ADS-B data, store in a PostgreSQL database, and use H3 to create files ready for heatmap visualizations.
![Screenshot 2024-11-11 175357](https://github.com/user-attachments/assets/6edbed66-2ec3-48d8-a0a2-541c027987d2)

I originally began this project mostly out of curiosity, but also because I wanted to do something with real world data and incorporate SQL. I'd used SQL before, but this was one of my first projects incorporating it into a script/program and automatically creating tables/storing data via Python. 

The script has functions to query an API for ADS-B data from aircraft in a given area. The API I used has a maximum of 250 nautical miles for the radius of this circle, so I created a function to query multiple points at once, remove duplicates, and store that data in a PostgreSQL database. I also knew I wanted to create visualizations for this data I was collecting, which lead me to Uber's H3 library. 

H3 splits the globe into hexagons (and a couple pentagons), with 16 different resolutions or "zoom levels" available. Using this, I take the data stored in the SQL table and convert the points for each flight into H3 cells of the specified resolution. Then, I use these to create WKT formatted Polygons and output the frequency/count of data points in each cell/polygon to a file in WKT format. This then makes it rather easy to use this file in QGIS to create a heatmap, showing the areas where planes most often traverse. 

![Screenshot 2024-11-11 175756](https://github.com/user-attachments/assets/9913b6f2-b87a-49fd-9357-7b422b3c4a0a)

I found that by combining multiple resolutions and overlaying them on top of one another you can create a heatmap with more information, instead of having two separate heatmaps for different resolutions. For example, using a broader resolution allows us to see more generally where planes commonly transit, and overlaying a more granular resolution level augments this and shows more detail about their paths within that area. The images above are created using a single resolution, while the images below were created using multiple. It does result in a heatmap thats more dense in information and might be harder to interpret, but depending on the need/use case I think these could perhaps be useful and informative. I mostly just find them fun to make and look at, which is a plus.

![Screenshot 2024-11-11 173626](https://github.com/user-attachments/assets/2aa0b0d0-0cc7-4090-8454-59c41776bd52)

![Screenshot 2024-11-09 200515](https://github.com/user-attachments/assets/f4c86c6e-d9b4-4863-b2f8-e6516f5cb2d9)

You might notice that there are some gaps and hard edges to the heatmaps, which are both artifacts of the method that the API I used has you structure queries for this data, using circles of no more than 250 nautical miles in radius. This could be overcome using more or better aligned circles, but I didn't want to flood the API with requests every 60s, thus I opted to accept the imperfect nature of the circles I used. I attempted to capture as much of the continental US as I could, you can see the areas I was querying below.

![Screenshot 2025-01-02 165643](https://github.com/user-attachments/assets/fdd30c50-6e6c-4e6f-ba7b-22444f1a6ce6)
