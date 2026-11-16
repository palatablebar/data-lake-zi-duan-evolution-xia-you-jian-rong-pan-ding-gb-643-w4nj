-- fieldmap 元数据导出 v2026_03（第一次改名：track_code -> tracking_no）
CREATE TABLE dim_shipment (
  `ship_id`      BIGINT        NOT NULL,  -- fid=5001
  `tracking_no`  VARCHAR(40)   NOT NULL,  -- fid=5002
  `dest_city`    VARCHAR(32)   NULL       -- fid=5003
);
