CREATE DATABASE IF NOT EXISTS x100_demo CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE x100_demo;
CREATE TABLE IF NOT EXISTS orders (
  order_id VARCHAR(32) PRIMARY KEY,
  owner_id VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  ordered_at DATE NOT NULL,
  item_summary VARCHAR(128) NOT NULL,
  eta DATE NULL
);
INSERT IGNORE INTO orders VALUES
('ORD-DEMO-1001','demo-user','运输中','2026-09-17','X100 主机','2026-09-26'),
('ORD-DEMO-1002','other-user','已签收','2026-09-18','X100 配件','2026-09-23');
