-- fieldmap 元数据导出 v2025_12（最早版本：字段还是最初的名字）
CREATE TABLE dim_shipment (
  `ship_id`     BIGINT        NOT NULL,  -- fid=5001
  `track_code`  VARCHAR(40)   NOT NULL,  -- fid=5002
  `dest_city`   VARCHAR(32)   NULL       -- fid=5003
);
