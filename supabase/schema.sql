-- HyperGridBot Supabase Schema
-- Run this in Supabase SQL Editor to create the database structure

-- Enable Row Level Security
ALTER DATABASE postgres SET "app.jwt_secret" TO 'your-jwt-secret';

-- Users table (core user data)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id BIGINT UNIQUE NOT NULL,
    telegram_username TEXT,
    binance_api_key_encrypted TEXT,
    binance_api_secret_encrypted TEXT,
    subscription_tier TEXT DEFAULT 'free' CHECK (subscription_tier IN ('free', 'basic', 'pro')),
    subscription_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- User trading configurations
CREATE TABLE IF NOT EXISTS user_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    pair TEXT DEFAULT 'BNBUSDT',
    preset TEXT DEFAULT 'NEUTRAL',
    custom_leverage INT CHECK (custom_leverage >= 1 AND custom_leverage <= 10),
    custom_grids INT CHECK (custom_grids >= 3 AND custom_grids <= 20),
    custom_spacing DECIMAL(10, 6) CHECK (custom_spacing >= 0.0005 AND custom_spacing <= 0.01),
    is_active BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, pair)
);

-- Payment/Transaction history
CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    amount_usdt DECIMAL(10, 2) NOT NULL,
    tx_hash TEXT,
    tier TEXT NOT NULL CHECK (tier IN ('basic', 'pro')),
    duration_days INT DEFAULT 30,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'expired')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    confirmed_at TIMESTAMPTZ
);

-- Bot activity logs (for analytics)
CREATE TABLE IF NOT EXISTS bot_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,  -- 'start', 'stop', 'trade', 'error'
    pair TEXT,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_user_configs_user_id ON user_configs(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_bot_logs_user_id ON bot_logs(user_id);

-- Row Level Security Policies
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_logs ENABLE ROW LEVEL SECURITY;

-- Function to auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_configs_updated_at
    BEFORE UPDATE ON user_configs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Helper function to check subscription status
CREATE OR REPLACE FUNCTION is_subscription_active(user_telegram_id BIGINT)
RETURNS BOOLEAN AS $$
DECLARE
    result BOOLEAN;
BEGIN
    SELECT (subscription_tier != 'free' AND subscription_expires_at > NOW())
    INTO result
    FROM users
    WHERE telegram_id = user_telegram_id;
    
    RETURN COALESCE(result, false);
END;
$$ LANGUAGE plpgsql;
