-- fieldmap 元数据导出 v2026_09（第二次改名 tracking_no -> waybill_code；
-- 过渡名 tracking_no 被另一个身份 fid=5004 占用，老报表按旧名取数会读错列）
CREATE TABLE dim_shipment (
  `ship_id`      BIGINT        NOT NULL,  -- fid=5001
  `waybill_code` VARCHAR(40)   NOT NULL,  -- fid=5002
  `tracking_no`  VARCHAR(16)   NULL,      -- fid=5004 新占用者，与 fid=5002 不同身份
  `dest_city`    VARCHAR(32)   NULL       -- fid=5003
);
