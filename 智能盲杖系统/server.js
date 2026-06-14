const express = require('express');
const cors = require('cors');
const bodyParser = require('body-parser');
const fs = require('fs');
const path = require('path');

const app = express();
const PORT = 3000;

app.use(cors());
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));

const DATA_DIR = path.join(__dirname, 'data');
if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
}

const LOCATION_LOG_FILE = path.join(DATA_DIR, 'location_logs.json');
const USERS_FILE = path.join(DATA_DIR, 'users.json');
const CONTACTS_FILE = path.join(DATA_DIR, 'contacts.json');
const NAV_HISTORY_FILE = path.join(DATA_DIR, 'navigation_history.json');

function initFile(filePath, defaultContent) {
    if (!fs.existsSync(filePath)) {
        fs.writeFileSync(filePath, JSON.stringify(defaultContent, null, 2));
    }
}

initFile(LOCATION_LOG_FILE, []);
initFile(USERS_FILE, []);
initFile(CONTACTS_FILE, []);
initFile(NAV_HISTORY_FILE, []);

function readData(filePath) {
    try {
        const data = fs.readFileSync(filePath, 'utf8');
        return JSON.parse(data);
    } catch (e) {
        return [];
    }
}

function saveData(filePath, data) {
    try {
        fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
        return true;
    } catch (e) {
        return false;
    }
}

app.post('/api/location/log', (req, res) => {
    try {
        const { userId, lat, lng, accuracy, timestamp } = req.body;
        
        if (!userId || !lat || !lng) {
            return res.status(400).json({ success: false, message: '缺少必要参数' });
        }
        
        const logEntry = {
            id: Date.now(),
            userId,
            lat: parseFloat(lat),
            lng: parseFloat(lng),
            accuracy: parseFloat(accuracy) || 0,
            timestamp: timestamp || new Date().toISOString(),
            createTime: new Date().toISOString()
        };
        
        const logs = readData(LOCATION_LOG_FILE);
        logs.push(logEntry);
        saveData(LOCATION_LOG_FILE, logs);
        
        res.json({ success: true, message: '定位记录保存成功', data: logEntry });
    } catch (e) {
        res.status(500).json({ success: false, message: '服务器内部错误' });
    }
});

app.get('/api/location/logs', (req, res) => {
    try {
        const { userId, startDate, endDate, limit = 100 } = req.query;
        let logs = readData(LOCATION_LOG_FILE);
        
        if (userId) {
            logs = logs.filter(log => log.userId === userId);
        }
        if (startDate) {
            logs = logs.filter(log => log.timestamp >= startDate);
        }
        if (endDate) {
            logs = logs.filter(log => log.timestamp <= endDate);
        }
        
        logs.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        logs = logs.slice(0, parseInt(limit));
        
        res.json({ success: true, data: logs });
    } catch (e) {
        res.status(500).json({ success: false, message: '服务器内部错误' });
    }
});

app.get('/api/location/today', (req, res) => {
    try {
        const { userId } = req.query;
        const today = new Date().toISOString().split('T')[0];
        let logs = readData(LOCATION_LOG_FILE);
        
        logs = logs.filter(log => log.timestamp.split('T')[0] === today);
        
        if (userId) {
            logs = logs.filter(log => log.userId === userId);
        }
        
        res.json({ success: true, data: logs });
    } catch (e) {
        res.status(500).json({ success: false, message: '服务器内部错误' });
    }
});

app.get('/api/location/stats', (req, res) => {
    try {
        const { userId } = req.query;
        let logs = readData(LOCATION_LOG_FILE);
        
        if (userId) {
            logs = logs.filter(log => log.userId === userId);
        }
        
        const today = new Date().toISOString().split('T')[0];
        const todayLogs = logs.filter(log => log.timestamp.split('T')[0] === today);
        
        const todayCount = todayLogs.length;
        const totalCount = logs.length;
        
        function calculateDistance(lat1, lng1, lat2, lng2) {
            const R = 6371000;
            const dLat = (lat2 - lat1) * Math.PI / 180;
            const dLng = (lng2 - lng1) * Math.PI / 180;
            const a = 
                Math.sin(dLat/2) * Math.sin(dLat/2) +
                Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * 
                Math.sin(dLng/2) * Math.sin(dLng/2);
            const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
            return R * c;
        }
        
        let todayDistance = 0;
        if (todayLogs.length >= 2) {
            for (let i = 1; i < todayLogs.length; i++) {
                const prev = todayLogs[i-1];
                const curr = todayLogs[i];
                todayDistance += calculateDistance(prev.lat, prev.lng, curr.lat, curr.lng);
            }
        }
        
        let totalDistance = 0;
        if (logs.length >= 2) {
            for (let i = 1; i < logs.length; i++) {
                const prev = logs[i-1];
                const curr = logs[i];
                totalDistance += calculateDistance(prev.lat, prev.lng, curr.lat, curr.lng);
            }
        }
        
        res.json({
            success: true,
            data: {
                todayCount,
                totalCount,
                todayDistance: (todayDistance / 1000).toFixed(2),
                totalDistance: (totalDistance / 1000).toFixed(2),
                lastLocation: logs.length > 0 ? logs[logs.length - 1] : null
            }
        });
    } catch (e) {
        res.status(500).json({ success: false, message: '服务器内部错误' });
    }
});

app.delete('/api/location/logs', (req, res) => {
    try {
        const { userId } = req.query;
        
        if (userId) {
            let logs = readData(LOCATION_LOG_FILE);
            logs = logs.filter(log => log.userId !== userId);
            saveData(LOCATION_LOG_FILE, logs);
        } else {
            saveData(LOCATION_LOG_FILE, []);
        }
        
        res.json({ success: true, message: '定位记录已清除' });
    } catch (e) {
        res.status(500).json({ success: false, message: '服务器内部错误' });
    }
});

app.post('/api/users', (req, res) => {
    try {
        const { username, password, phone } = req.body;
        
        if (!username || !password) {
            return res.status(400).json({ success: false, message: '缺少必要参数' });
        }
        
        const users = readData(USERS_FILE);
        const exists = users.find(u => u.username === username);
        
        if (exists) {
            return res.status(400).json({ success: false, message: '用户名已存在' });
        }
        
        const user = {
            id: Date.now(),
            username,
            password,
            phone: phone || '',
            createdAt: new Date().toISOString()
        };
        
        users.push(user);
        saveData(USERS_FILE, users);
        
        res.json({ success: true, message: '用户注册成功', data: user });
    } catch (e) {
        res.status(500).json({ success: false, message: '服务器内部错误' });
    }
});

app.post('/api/users/login', (req, res) => {
    try {
        const { username, password } = req.body;
        
        if (!username || !password) {
            return res.status(400).json({ success: false, message: '缺少必要参数' });
        }
        
        const users = readData(USERS_FILE);
        const user = users.find(u => u.username === username && u.password === password);
        
        if (!user) {
            return res.status(401).json({ success: false, message: '用户名或密码错误' });
        }
        
        res.json({ success: true, message: '登录成功', data: user });
    } catch (e) {
        res.status(500).json({ success: false, message: '服务器内部错误' });
    }
});

app.get('/api/contacts/:userId', (req, res) => {
    try {
        const { userId } = req.params;
        const contacts = readData(CONTACTS_FILE);
        const userContacts = contacts.filter(c => c.userId === userId);
        res.json({ success: true, data: userContacts });
    } catch (e) {
        res.status(500).json({ success: false, message: '服务器内部错误' });
    }
});

app.post('/api/contacts', (req, res) => {
    try {
        const { userId, name, phone, wechatId, qqNumber, isDefault } = req.body;
        
        if (!userId || !name || !phone) {
            return res.status(400).json({ success: false, message: '缺少必要参数' });
        }
        
        const contacts = readData(CONTACTS_FILE);
        const defaultCount = contacts.filter(c => c.userId === userId && c.isDefault).length;
        
        if (isDefault && defaultCount >= 5) {
            return res.status(400).json({ success: false, message: '默认联系人最多5个' });
        }
        
        const contact = {
            id: Date.now(),
            userId,
            name,
            phone,
            wechatId: wechatId || '',
            qqNumber: qqNumber || '',
            isDefault: isDefault || false,
            createdAt: new Date().toISOString()
        };
        
        contacts.push(contact);
        saveData(CONTACTS_FILE, contacts);
        
        res.json({ success: true, message: '联系人添加成功', data: contact });
    } catch (e) {
        res.status(500).json({ success: false, message: '服务器内部错误' });
    }
});

app.put('/api/contacts/:id', (req, res) => {
    try {
        const { id } = req.params;
        const { name, phone, wechatId, qqNumber, isDefault } = req.body;
        
        const contacts = readData(CONTACTS_FILE);
        const index = contacts.findIndex(c => c.id === parseInt(id));
        
        if (index === -1) {
            return res.status(404).json({ success: false, message: '联系人不存在' });
        }
        
        if (isDefault) {
            const userId = contacts[index].userId;
            const defaultCount = contacts.filter(c => c.userId === userId && c.isDefault && c.id !== parseInt(id)).length;
            if (defaultCount >= 5) {
                return res.status(400).json({ success: false, message: '默认联系人最多5个' });
            }
        }
        
        contacts[index] = {
            ...contacts[index],
            name: name || contacts[index].name,
            phone: phone || contacts[index].phone,
            wechatId: wechatId !== undefined ? wechatId : contacts[index].wechatId,
            qqNumber: qqNumber !== undefined ? qqNumber : contacts[index].qqNumber,
            isDefault: isDefault !== undefined ? isDefault : contacts[index].isDefault
        };
        
        saveData(CONTACTS_FILE, contacts);
        
        res.json({ success: true, message: '联系人更新成功', data: contacts[index] });
    } catch (e) {
        res.status(500).json({ success: false, message: '服务器内部错误' });
    }
});

app.delete('/api/contacts/:id', (req, res) => {
    try {
        const { id } = req.params;
        let contacts = readData(CONTACTS_FILE);
        const index = contacts.findIndex(c => c.id === parseInt(id));
        
        if (index === -1) {
            return res.status(404).json({ success: false, message: '联系人不存在' });
        }
        
        contacts.splice(index, 1);
        saveData(CONTACTS_FILE, contacts);
        
        res.json({ success: true, message: '联系人删除成功' });
    } catch (e) {
        res.status(500).json({ success: false, message: '服务器内部错误' });
    }
});

app.post('/api/navigation', (req, res) => {
    try {
        const { userId, startPoint, endPoint, distance, duration, steps } = req.body;
        
        if (!userId || !startPoint || !endPoint) {
            return res.status(400).json({ success: false, message: '缺少必要参数' });
        }
        
        const history = readData(NAV_HISTORY_FILE);
        const navRecord = {
            id: Date.now(),
            userId,
            startPoint,
            endPoint,
            distance: parseFloat(distance) || 0,
            duration: parseInt(duration) || 0,
            steps: steps || [],
            startTime: new Date().toISOString(),
            status: 'completed'
        };
        
        history.push(navRecord);
        saveData(NAV_HISTORY_FILE, history);
        
        res.json({ success: true, message: '导航记录保存成功', data: navRecord });
    } catch (e) {
        res.status(500).json({ success: false, message: '服务器内部错误' });
    }
});

app.get('/api/navigation/:userId', (req, res) => {
    try {
        const { userId } = req.params;
        const history = readData(NAV_HISTORY_FILE);
        const userHistory = history.filter(h => h.userId === userId);
        userHistory.sort((a, b) => new Date(b.startTime) - new Date(a.startTime));
        res.json({ success: true, data: userHistory });
    } catch (e) {
        res.status(500).json({ success: false, message: '服务器内部错误' });
    }
});

app.get('/api/health', (req, res) => {
    res.json({ success: true, message: '服务器运行正常', timestamp: new Date().toISOString() });
});

app.listen(PORT, () => {
    console.log(`🚀 智能盲杖后端服务已启动`);
    console.log(`📍 服务地址: http://localhost:${PORT}`);
});