-- 시드: 5지점 (config/sites.yaml 좌표·가중치, T6)
insert into sites (site_id,name,basin,facility_type,facility_name,lat,lon,intake_weight,intake_capacity_tpd,catchment_area_km2,meta) values
('2011G26','해평','낙동강','weir','칠곡보',36.1695,128.3873,0.5,464000,11040,'{"station_id":"HP"}'::jsonb),
('2011G56','강정·고령','낙동강','weir','강정고령보',35.843,128.453,0.8,770000,11667,'{"station_id":"GJGR"}'::jsonb),
('2020G33','칠서','낙동강','weir','창녕함안보',35.37,128.48,0.5,440000,20697,'{"station_id":"CS"}'::jsonb),
('2022G05','물금·매리','낙동강','weir','낙동강하굿둑',35.31,128.99,1.0,840000,23560,'{"station_id":"MGMR"}'::jsonb),
('3008G30','회남','금강','dam','대청댐',36.4,127.6,0.7,1350000,3204,'{"station_id":"DCHN"}'::jsonb)
on conflict (site_id) do update set name=excluded.name, basin=excluded.basin, facility_type=excluded.facility_type, facility_name=excluded.facility_name, lat=excluded.lat, lon=excluded.lon, intake_weight=excluded.intake_weight, intake_capacity_tpd=excluded.intake_capacity_tpd, catchment_area_km2=excluded.catchment_area_km2, meta=excluded.meta;
