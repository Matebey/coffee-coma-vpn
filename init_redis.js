// Инициализация Redis при первом запуске
const redis = require('redis');
const client = redis.createClient();

client.on('connect', () => {
    console.log('✅ Connected to Redis');
    
    // Инициализация счетчиков
    client.set('stats:total_users', 0);
    client.set('stats:active_users', 0);
    client.set('stats:total_income', 0);
    
    console.log('✅ Redis initialized successfully');
    client.quit();
});

client.on('error', (err) => {
    console.log('❌ Redis error:', err);
});