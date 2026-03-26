-- ClickHouse SQL export
-- database: default

CREATE TABLE `default`.`a_table` (`id` UInt32) ENGINE = MergeTree ORDER BY tuple();
TRUNCATE TABLE `default`.`a_table`;
INSERT INTO `default`.`a_table` (`id`) VALUES (1);

CREATE TABLE `default`.`z_table` (`id` UInt32) ENGINE = MergeTree ORDER BY tuple();
TRUNCATE TABLE `default`.`z_table`;
INSERT INTO `default`.`z_table` (`id`) VALUES (2);

