import geopandas as gpd
import pandas as pd
import requests
import time

# === НАСТРОЙКИ (ИЗМЕНИ РАДИУС) ===
VK_TOKEN = ""
VK_VERSION = "5.131"
RADIUS = 500          # УВЕЛИЧЕННЫЙ радиус 500м
BATCH_SIZE = 1000
PAUSE_POINT = 3       # Пауза между точками
PAUSE_BATCH = 0.35    # Пауза между offset

print(" Загрузка трансектов...")
gdf_trans = gpd.read_file("transects_gdf_m.shp")

# Подготовка точек
if gdf_trans.geom_type[0] != 'Point':
    gdf_trans['geometry'] = gpd.points_from_xy(gdf_trans.POINT_X, gdf_trans.POINT_Y)
    gdf_trans = gdf_trans.set_crs("EPSG:4326")

print(f" {len(gdf_trans)} трансектов готовы")

# === ГЛАВНЫЙ ЦИКЛ ===
print("\n VK сбор данных...")
all_results = []
seen_photos = set()  # АНТИДУБЛИ по photo_id+owner_id

for idx, point in gdf_trans.iterrows():
    lat, lon = point.POINT_Y, point.POINT_X
    print(f"\n[{idx+1}/{len(gdf_trans)}] {lat:.5f}, {lon:.5f}")
    
    offset = 0
    local_count = 0
    
    while True:
        params = {
            "access_token": VK_TOKEN,
            "v": VK_VERSION,
            "lat": lat,
            "long": lon,
            "radius": RADIUS,
            "count": BATCH_SIZE,
            "offset": offset
        }
        
        resp = requests.get("https://api.vk.com/method/photos.search", params=params).json()
        
        if "response" not in resp or not resp["response"]["items"]:
            break
            
        items = resp["response"]["items"]
        
        for ph in items:
            photo_key = (ph['id'], ph['owner_id'])
            if photo_key in seen_photos:
                continue  # ПРОПУСК ДУБЛЕЙ
                
            seen_photos.add(photo_key)
            
            photo_lat = ph.get('lat')
            photo_lon = ph.get('long')
            is_geotagged = (photo_lat is not None and photo_lon is not None)
            
            all_results.append({
                'transect_id': idx,
                'transect_name': gdf_trans.iloc[idx].get('name', f'point_{idx}'),
                'query_lat': lat,
                'query_lon': lon,
                'photo_lat': photo_lat,
                'photo_lon': photo_lon,
                'is_geotagged': is_geotagged,
                'photo_id': ph['id'],
                'owner_id': ph['owner_id'],
                'likes': ph.get('likes', {}).get('count', 0),
                'date': ph.get('date')
            })
            local_count += 1
        
        print(f"  offset={offset}: +{local_count} уникальных")
        offset += BATCH_SIZE
        time.sleep(PAUSE_BATCH)
        
        if len(items) < BATCH_SIZE:
            break
    
    print(f"  Точка: {local_count} фото")
    time.sleep(PAUSE_POINT)

# === СТАТИСТИКА ===
df_vk = pd.DataFrame(all_results)
stats = df_vk.groupby('transect_id').agg({
    'photo_id': 'count',                    # total_posts
    'is_geotagged': lambda x: x.sum()       # geotagged_posts
}).rename(columns={'photo_id': 'total_posts', 'is_geotagged': 'geotagged_posts'})

stats['ratio_pct'] = (stats['geotagged_posts'] / stats['total_posts'] * 100).round(1)
stats['total_likes'] = df_vk.groupby('transect_id')['likes'].sum().round(0)
stats['load_index'] = (stats['geotagged_posts'] * stats['total_likes'] / 100).round(1)
stats = stats.reset_index()
stats['transect_name'] = [gdf_trans.iloc[i].get('name', f'point_{i}') for i in stats.transect_id]

# === ЭКСПОРТ CSV ===
csv_data = f"vk_transects_r{RADIUS}m_full.csv"
csv_stats = f"vk_transects_r{RADIUS}m_stats.csv"
df_vk.to_csv(csv_data, index=False)
stats.to_csv(csv_stats, index=False)

# === ЭКСПОРТ SHP + GPKG ===
# 1. Статистика по трансектам
gdf_stats = gpd.GeoDataFrame(
    stats,
    geometry=gpd.points_from_xy(
        stats.transect_id.map(lambda i: gdf_trans.iloc[i].POINT_X),
        stats.transect_id.map(lambda i: gdf_trans.iloc[i].POINT_Y)
    ),
    crs="EPSG:4326"
)
gdf_stats.to_file(f"vk_transects_r{RADIUS}m_stats.shp")

# 2. Геотеганные фото
geo_photos = df_vk[df_vk.is_geotagged].copy()
gdf_geo = gpd.GeoDataFrame(
    geo_photos[['photo_id', 'likes', 'transect_id']],
    geometry=gpd.points_from_xy(geo_photos.photo_lon, geo_photos.photo_lat),
    crs="EPSG:4326"
)
gdf_geo.to_file(f"vk_photos_r{RADIUS}m.shp")

# 3. Полный GPKG
gdf_vk_final = gpd.GeoDataFrame(
    gdf_trans[['POINT_X', 'POINT_Y']].iloc[stats.transect_id],
    geometry=gpd.points_from_xy(gdf_trans.POINT_X.iloc[stats.transect_id], gdf_trans.POINT_Y.iloc[stats.transect_id]),
    crs="EPSG:4326"
)
for col in stats.columns:
    gdf_vk_final[col] = stats[col]

gdf_vk_final.to_file(f"vk_transects_r{RADIUS}m.gpkg", driver="GPKG")

# === ОТчёт ===
print(f"\n ВСЕ РЕЗУЛЬТАТЫ (RADIUS={RADIUS}m):")
print(f" Постов: {len(df_vk):,} | Геотегов: {df_vk.is_geotagged.sum():,}")
print(f" {csv_data} | {csv_stats}")
print(f"  vk_transects_r{RADIUS}m_stats.shp | vk_photos_r{RADIUS}m.shp | vk_transects_r{RADIUS}m.gpkg")
print("\n ТОП-5 по load_index:")
print(stats.nlargest(5, 'load_index')[['transect_name', 'total_posts', 'geotagged_posts', 'load_index']])

df_vk.head()
