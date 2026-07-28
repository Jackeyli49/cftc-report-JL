const fs = require('fs');
const path = require('path');
const out = path.join(__dirname, 'dist');
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });
fs.copyFileSync(path.join(__dirname, 'index.html'), path.join(out, 'index.html'));
fs.cpSync(path.join(__dirname, 'data'), path.join(out, 'data'), { recursive: true });
console.log('Static site built in dist/');
