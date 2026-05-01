-- 添加prediction_period列到match_predictions表
ALTER TABLE match_predictions ADD COLUMN prediction_period VARCHAR(20) DEFAULT 'pre_24h';

-- 为现有记录设置默认值为pre_24h
UPDATE match_predictions SET prediction_period = 'pre_24h' WHERE prediction_period IS NULL;

-- 移除fixture_id的唯一约束（如果需要的话）
-- 注意：SQLite不支持直接删除唯一约束，需要重建表

-- 创建新表结构（移除fixture_id的唯一约束）
CREATE TABLE match_predictions_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fixture_id VARCHAR(50),
    match_num VARCHAR(50),
    league VARCHAR(100),
    home_team VARCHAR(100),
    away_team VARCHAR(100),
    match_time DATETIME,
    prediction_period VARCHAR(20) DEFAULT 'pre_24h',
    raw_data TEXT,
    prediction_text TEXT,
    predicted_result VARCHAR(50),
    confidence INTEGER,
    actual_result VARCHAR(50),
    actual_score VARCHAR(50),
    is_correct BOOLEAN,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 复制现有数据到新表
INSERT INTO match_predictions_new (
    id, fixture_id, match_num, league, home_team, away_team, match_time,
    prediction_period, raw_data, prediction_text, predicted_result, confidence,
    actual_result, actual_score, is_correct, created_at, updated_at
) SELECT 
    id, fixture_id, match_num, league, home_team, away_team, match_time,
    'pre_24h', raw_data, prediction_text, predicted_result, confidence,
    actual_result, actual_score, is_correct, created_at, updated_at
FROM match_predictions;

-- 删除旧表
DROP TABLE match_predictions;

-- 重命名新表
ALTER TABLE match_predictions_new RENAME TO match_predictions;

-- 创建索引
CREATE INDEX idx_fixture_id ON match_predictions(fixture_id);
CREATE INDEX idx_prediction_period ON match_predictions(prediction_period);
CREATE INDEX idx_fixture_period ON match_predictions(fixture_id, prediction_period);