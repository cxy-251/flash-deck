        (function() {
            if (!window.location.pathname.startsWith('/game/')) {
                return;
            }

            // 1. 全局 Buffer 对象模拟 (支持 Base64 与多编码转换)
            window.Buffer = {
                isBuffer: function(obj) { return obj instanceof ArrayBuffer || obj instanceof Uint8Array; },
                from: function(data, enc) {
                    if (enc === 'base64' && typeof data === 'string') {
                        try {
                            var decoded = atob(data);
                            return {
                                toString: function(type) { return decoded; }
                            };
                        } catch(e) {}
                    }
                    if (typeof data === 'string') {
                        return { toString: function() { return data; } };
                    }
                    return { toString: function() { return String(data); } };
                },
                alloc: function(size) { return new Uint8Array(size); },
                concat: function(list) { return list; }
            };

            // 2. nw 全局运行环境模拟 (完整模拟 Menu / MenuItem / Clipboard / Window)
            function NwMenu() {
                this.items = [];
            }
            NwMenu.prototype.append = function(item) { this.items.push(item); };
            NwMenu.prototype.popup = function() {};
            NwMenu.prototype.insert = function() {};
            NwMenu.prototype.remove = function() {};

            function NwMenuItem(opt) {
                this.label = (opt && opt.label) || '';
                this.click = (opt && opt.click) || function() {};
                this.submenu = (opt && opt.submenu) || null;
            }

            var nwWin = {
                menu: new NwMenu(),
                isPlugin: false,
                showDevTools: function() {},
                closeDevTools: function() {},
                close: function() {},
                maximize: function() {},
                minimize: function() {},
                restore: function() {},
                enterFullscreen: function() {},
                leaveFullscreen: function() {},
                toggleFullscreen: function() {},
                setAlwaysOnTop: function() {},
                moveBy: function() {},
                moveTo: function() {},
                resizeBy: function() {},
                resizeTo: function() {},
                isFullscreen: false,
                zoomLevel: 0,
                x: 0, y: 0,
                width: window.innerWidth,
                height: window.innerHeight,
                on: function() {},
                once: function() {},
                removeListener: function() {},
                removeAllListeners: function() {},
                show: function() {},
                hide: function() {},
                focus: function() {},
                blur: function() {},
                evalNWBin: function(frame, path) {}
            };

            window.nw = {
                App: {
                    argv: [],
                    fullArgv: [],
                    manifest: { name: "rpg_game", main: "index.html" },
                    quit: function() {},
                    closeAllWindows: function() {},
                    dataPath: ""
                },
                Window: {
                    get: function() { return nwWin; }
                },
                Clipboard: {
                    get: function() {
                        return {
                            get: function() { return ''; },
                            set: function() {},
                            clear: function() {}
                        };
                    }
                },
                Shell: {
                    openExternal: function(url) { window.open(url); },
                    openItem: function() {}
                },
                Menu: NwMenu,
                MenuItem: NwMenuItem,
                require: function(mod) { return window.require(mod); }
            };

            // 3. process 全局运行环境模拟
            window.process = {
                platform: 'win32',
                arch: 'x64',
                argv: [],
                versions: {
                    'node-webkit': '0.45.0',
                    'nw': '0.45.0',
                    'node': '14.0.0',
                    'chromium': '80.0.0'
                },
                env: { APPDATA: '', LOCALAPPDATA: '', USERPROFILE: '' },
                cwd: function() { return '.'; },
                mainModule: { filename: 'index.html' },
                nextTick: function(fn) { setTimeout(fn, 0); },
                on: function() {},
                exit: function() {},
                hrtime: function(time) {
                    var t = performance.now() / 1000;
                    var s = Math.floor(t);
                    var n = Math.floor((t % 1) * 1e9);
                    if (time) {
                        s -= time[0];
                        n -= time[1];
                        if (n < 0) { s--; n += 1e9; }
                    }
                    return [s, n];
                }
            };

            // 4. Node.js 常用模块全功能模拟 (fs, path, os, greenworks)
            var mockFs = {
                existsSync: function(p) {
                    if (typeof p !== 'string') return false;
                    if (p.indexOf('config.rpgsave') >= 0 || p === 'lng.txt') return true;
                    var reqPath = p;
                    var gid = window.gameId || '';
                    if (!gid && typeof window !== 'undefined' && window.location) {
                        var pathParts = window.location.pathname.split('/');
                        if (pathParts.length >= 3 && pathParts[1] === 'game') {
                            gid = pathParts[2];
                        }
                    }
                    var gameRootStr1 = '/games/';
                    var gameRootStr2 = '/game/' + gid + '/';
                    var gameRootStr3 = '/game/' + gid;
                    
                    var idx = p.indexOf(gameRootStr1);
                    if (idx >= 0) {
                        var parts = p.substring(idx + gameRootStr1.length).split('/');
                        if (parts.length > 1) {
                            parts.shift(); // remove gameId
                            reqPath = parts.join('/');
                        }
                    } else if (p.startsWith(gameRootStr2)) {
                        reqPath = p.substring(gameRootStr2.length);
                    } else if (p === gameRootStr3) {
                        reqPath = '';
                    }

                    while (reqPath.startsWith('/')) {
                        reqPath = reqPath.substring(1);
                    }

                    if (reqPath.indexOf('locales') >= 0 && reqPath.indexOf('.json') === -1) {
                        return true;
                    }
                    var xhr = new XMLHttpRequest();
                    if (reqPath.endsWith('.rpgsave') || reqPath.endsWith('.rmmzsave') || reqPath.endsWith('.rmmzsave_') || reqPath.endsWith('.save') || reqPath.endsWith('.bak')) {
                        var gid2 = window.gameId || (decodeURIComponent(window.location.pathname.split('/')[2]));
                        var filename = reqPath;
                        var slashIdx = reqPath.lastIndexOf('/');
                        if (slashIdx >= 0) filename = reqPath.substring(slashIdx + 1);
                        else {
                            var backslashIdx = reqPath.lastIndexOf('\\\\');
                            if (backslashIdx >= 0) filename = reqPath.substring(backslashIdx + 1);
                        }
                        xhr.open('HEAD', '/save/' + encodeURIComponent(gid2) + '/' + encodeURIComponent(filename) + '?t=' + Date.now(), false);
                    } else {
                        xhr.open('HEAD', reqPath + '?t=' + Date.now(), false);
                    }
                    try {
                        xhr.send();
                        var res = (xhr.status === 200);
                        if (res) return true;
                    } catch(e) {}
                    
                    // Fallback to encrypted extensions
                    var extMap = {
                        '.png': '.rpgmvp',
                        '.ogg': '.rpgmvo',
                        '.m4a': '.rpgmvm'
                    };
                    for (var ext in extMap) {
                        if (reqPath.endsWith(ext)) {
                            var encPath = reqPath.substring(0, reqPath.length - ext.length) + extMap[ext];
                            var xhrEnc = new XMLHttpRequest();
                            xhrEnc.open('HEAD', encPath + '?t=' + Date.now(), false);
                            try {
                                xhrEnc.send();
                                if (xhrEnc.status === 200) return true;
                            } catch(e) {}
                        }
                    }
                    return false;
                },
                readFileSync: function(p, enc) {
                    if (p === 'lng.txt') {
                        return 'cn';
                    }
                    if (!p.endsWith('.rpgsave') && !p.endsWith('.rmmzsave') && !p.endsWith('.rmmzsave_') && !p.endsWith('.bak')) {
                        var val = localStorage.getItem('fs_' + p);
                        if (val !== null) return val;
                    }
                    var reqPath = p;
                    var gid = window.gameId || '';
                    if (!gid && typeof window !== 'undefined' && window.location) {
                        var pathParts = window.location.pathname.split('/');
                        if (pathParts.length >= 3 && pathParts[1] === 'game') {
                            gid = pathParts[2];
                        }
                    }
                    var gameRootStr1 = '/games/';
                    var gameRootStr2 = '/game/' + gid + '/';
                    var gameRootStr3 = '/game/' + gid;
                    
                    var idx = p.indexOf(gameRootStr1);
                    if (idx >= 0) {
                        var parts = p.substring(idx + gameRootStr1.length).split('/');
                        if (parts.length > 1) {
                            parts.shift(); // remove gameId
                            reqPath = parts.join('/');
                        }
                    } else if (p.startsWith(gameRootStr2)) {
                        reqPath = p.substring(gameRootStr2.length);
                    } else if (p === gameRootStr3) {
                        reqPath = '';
                    }

                    while (reqPath.startsWith('/')) {
                        reqPath = reqPath.substring(1);
                    }

                    var xhr = new XMLHttpRequest();
                    if (reqPath.endsWith('.rpgsave') || reqPath.endsWith('.rmmzsave') || reqPath.endsWith('.rmmzsave_') || reqPath.endsWith('.save') || reqPath.endsWith('.bak')) {
                        var gid2 = window.gameId || (decodeURIComponent(window.location.pathname.split('/')[2]));
                        var filename = reqPath;
                        var slashIdx = reqPath.lastIndexOf('/');
                        if (slashIdx >= 0) filename = reqPath.substring(slashIdx + 1);
                        else {
                            var backslashIdx = reqPath.lastIndexOf('\\\\');
                            if (backslashIdx >= 0) filename = reqPath.substring(backslashIdx + 1);
                        }
                        xhr.open('GET', '/save/' + encodeURIComponent(gid2) + '/' + encodeURIComponent(filename) + '?t=' + Date.now(), false);
                    } else {
                        xhr.open('GET', reqPath + '?t=' + Date.now(), false);
                    }
                    try {
                        xhr.send();
                        if (xhr.status === 200) return xhr.responseText;
                    } catch(e) {}
                    
                    // Fallback to encrypted extensions
                    var extMap = {
                        '.png': '.rpgmvp',
                        '.ogg': '.rpgmvo',
                        '.m4a': '.rpgmvm'
                    };
                    for (var ext in extMap) {
                        if (reqPath.endsWith(ext)) {
                            var encPath = reqPath.substring(0, reqPath.length - ext.length) + extMap[ext];
                            var xhrEnc = new XMLHttpRequest();
                            xhrEnc.open('GET', encPath + '?t=' + Date.now(), false);
                            try {
                                xhrEnc.send();
                                if (xhrEnc.status === 200) return xhrEnc.responseText;
                            } catch(e) {}
                        }
                    }
                    return '';
                },
                createWriteStream: function(p) {
                    var buffer = '';
                    return {
                        write: function(chunk) {
                            buffer += (typeof chunk === 'string') ? chunk : new TextDecoder().decode(chunk);
                        },
                        end: function(chunk) {
                            if (chunk) buffer += (typeof chunk === 'string') ? chunk : new TextDecoder().decode(chunk);
                            localStorage.setItem('fs_' + p, buffer);
                            if (p === 'lng.txt') {
                                window.LngMode = buffer.trim();
                            }
                        },
                        on: function() {},
                        once: function() {},
                        emit: function() {}
                    };
                },
                readFile: function(p, enc, cb) {
                    var callback = typeof enc === 'function' ? enc : cb;
                    var res = this.readFileSync(p, typeof enc === 'string' ? enc : 'utf8');
                    setTimeout(function() {
                        if (res !== null && res !== '') {
                            if (typeof callback === 'function') callback(null, res);
                        } else {
                            if (typeof callback === 'function') callback(new Error("File not found"));
                        }
                    }, 0);
                },
                writeFileSync: function(p, data) {
                    var strData = (typeof data === 'string') ? data : String(data);
                    localStorage.setItem('fs_' + p, strData);
                    var filename = p;
                    var slashIdx = p.lastIndexOf('/');
                    if (slashIdx >= 0) filename = p.substring(slashIdx + 1);
                    else {
                        var backslashIdx = p.lastIndexOf('\\\\');
                        if (backslashIdx >= 0) filename = p.substring(backslashIdx + 1);
                    }
                    if (filename.endsWith('.rpgsave') || filename.endsWith('.rmmzsave') || filename.endsWith('.rmmzsave_') || filename.endsWith('.save') || filename.endsWith('.rpgsave.bak') || filename.endsWith('.rmmzsave.bak')) {
                        var gid = window.gameId || (decodeURIComponent(window.location.pathname.split('/')[2]));
                        var xhr = new XMLHttpRequest();
                        try {
                            xhr.open('POST', '/api/save/' + encodeURIComponent(gid) + '?file=' + encodeURIComponent(filename), false);
                            xhr.send(strData);
                        } catch(e) {}
                    }
                },
                writeFile: function(p, data, opt, cb) {
                    var callback = typeof opt === 'function' ? opt : cb;
                    var strData = (typeof data === 'string') ? data : String(data);
                    localStorage.setItem('fs_' + p, strData);
                    var filename = p;
                    var slashIdx = p.lastIndexOf('/');
                    if (slashIdx >= 0) filename = p.substring(slashIdx + 1);
                    else {
                        var backslashIdx = p.lastIndexOf('\\\\');
                        if (backslashIdx >= 0) filename = p.substring(backslashIdx + 1);
                    }
                    if (filename.endsWith('.rpgsave') || filename.endsWith('.rmmzsave') || filename.endsWith('.rmmzsave_') || filename.endsWith('.save') || filename.endsWith('.rpgsave.bak') || filename.endsWith('.rmmzsave.bak')) {
                        var gid = window.gameId || (decodeURIComponent(window.location.pathname.split('/')[2]));
                        var xhr = new XMLHttpRequest();
                        xhr.open('POST', '/api/save/' + encodeURIComponent(gid) + '?file=' + encodeURIComponent(filename), true);
                        xhr.onload = function() { if (typeof callback === 'function') callback(null); };
                        xhr.onerror = function() { if (typeof callback === 'function') callback(null); };
                        try { xhr.send(strData); } catch(e) { if (typeof callback === 'function') callback(null); }
                    } else {
                        setTimeout(function() {
                            if (typeof callback === 'function') callback(null);
                        }, 0);
                    }
                },
                appendFile: function(p, data, opt, cb) { var callback = cb || opt; if (typeof callback === 'function') callback(null); },
                appendFileSync: function(p, data) {},
                renameSync: function(oldPath, newPath) {
                    var data = this.readFileSync(oldPath);
                    if (data !== null && data !== '') {
                        this.writeFileSync(newPath, data);
                        this.unlinkSync(oldPath);
                    }
                },
                unlink: function(p, cb) {
                    this.unlinkSync(p);
                    if (typeof cb === 'function') cb(null);
                },
                mkdirSync: function(p) {},
                mkdir: function(p, cb) { if (typeof cb === 'function') cb(null); },
                statSync: function(p) {
                    var isDir = (p && (p.endsWith('/') || p.indexOf('.') === -1));
                    if (p && p.indexOf('locales') >= 0 && p.indexOf('.json') === -1) isDir = true;
                    return {
                        isFile: function() { return !isDir; },
                        isDirectory: function() { return isDir; },
                        mtime: new Date(),
                        size: 0
                    };
                },
                lstatSync: function(p) { return this.statSync(p); },
                readdirSync: function(p) {
                    var reqPath = p;
                    var gid = '';
                    if (typeof p === 'string') {
                        var pathParts = window.location.pathname.split('/');
                        if (pathParts.length >= 3 && pathParts[1] === 'game') {
                            gid = pathParts[2];
                        }
                        var gameRootStr1 = '/games/';
                        var gameRootStr2 = '/game/' + gid + '/';
                        var gameRootStr3 = '/game/' + gid;
                        var idx = p.indexOf(gameRootStr1);
                        if (idx >= 0) {
                            var parts = p.substring(idx + gameRootStr1.length).split('/');
                            if (parts.length > 1) {
                                parts.shift();
                                reqPath = parts.join('/');
                            }
                        } else if (p.startsWith(gameRootStr2)) {
                            reqPath = p.substring(gameRootStr2.length);
                        } else if (p === gameRootStr3) {
                            reqPath = '';
                        }
                    }
                    while (reqPath.startsWith('/')) {
                        reqPath = reqPath.substring(1);
                    }
                    var xhr = new XMLHttpRequest();
                    var apiUrl = '/api/readdir?path=' + encodeURIComponent(reqPath);
                    if (gid) { apiUrl += '&game_id=' + encodeURIComponent(gid); }
                    xhr.open('GET', apiUrl, false);
                    try {
                        xhr.send();
                        if (xhr.status === 200) {
                            return JSON.parse(xhr.responseText);
                        }
                    } catch(e) {}
                    return [];
                },
                readdir: function(p, cb) {
                    var reqPath = p;
                    var gid = '';
                    if (typeof p === 'string') {
                        var pathParts = window.location.pathname.split('/');
                        if (pathParts.length >= 3 && pathParts[1] === 'game') {
                            gid = pathParts[2];
                        }
                        var gameRootStr1 = '/games/';
                        var gameRootStr2 = '/game/' + gid + '/';
                        var gameRootStr3 = '/game/' + gid;
                        var idx = p.indexOf(gameRootStr1);
                        if (idx >= 0) {
                            var parts = p.substring(idx + gameRootStr1.length).split('/');
                            if (parts.length > 1) {
                                parts.shift();
                                reqPath = parts.join('/');
                            }
                        } else if (p.startsWith(gameRootStr2)) {
                            reqPath = p.substring(gameRootStr2.length);
                        } else if (p === gameRootStr3) {
                            reqPath = '';
                        }
                    }
                    var xhr = new XMLHttpRequest();
                    var apiUrl = '/api/readdir?path=' + encodeURIComponent(reqPath);
                    if (gid) apiUrl += '&game_id=' + encodeURIComponent(gid);
                    xhr.open('GET', apiUrl, true);
                    xhr.onload = function() {
                        if (xhr.status === 200) {
                            if (typeof cb === 'function') cb(null, JSON.parse(xhr.responseText));
                        } else {
                            if (typeof cb === 'function') cb(new Error("Not found"));
                        }
                    };
                    xhr.onerror = function() {
                        if (typeof cb === 'function') cb(new Error("Network Error"));
                    };
                    try { xhr.send(); } catch(e) { if (typeof cb === 'function') cb(e); }
                },
                unlinkSync: function(p) { localStorage.removeItem('fs_' + p); },
                unlink: function(p, cb) { localStorage.removeItem('fs_' + p); if (typeof cb === 'function') cb(null); },
                openSync: function(p, flags) { return 1; },
                open: function(p, flags, cb) { if (typeof cb === 'function') cb(null, 1); },
                readSync: function(fd, buf, offset, length, pos) { return 0; },
                read: function(fd, buf, offset, length, pos, cb) { if (typeof cb === 'function') cb(null, 0, buf); },
                closeSync: function(fd) {},
                close: function(fd, cb) { if (typeof cb === 'function') cb(null); }
            };

            var mockPath = {
                join: function() { return this.normalize(Array.prototype.slice.call(arguments).join('/')); },
                resolve: function() { return this.normalize(Array.prototype.slice.call(arguments).join('/')); },
                normalize: function(p) {
                    if (!p) return '.';
                    var isAbs = p.startsWith('/');
                    var parts = p.split('/');
                    var res = [];
                    for (var i = 0; i < parts.length; i++) {
                        var part = parts[i];
                        if (part === '' || part === '.') continue;
                        if (part === '..') {
                            if (res.length > 0 && res[res.length - 1] !== '..') res.pop();
                            else if (!isAbs) res.push('..');
                        } else {
                            res.push(part);
                        }
                    }
                    var finalStr = res.join('/');
                    if (isAbs) finalStr = '/' + finalStr;
                    if (p.endsWith('/') && finalStr !== '/') finalStr += '/';
                    return finalStr || '.';
                },
                isAbsolute: function(p) { return p && (p.startsWith('/') || p.indexOf(':') === 1); },
                relative: function(from, to) { return to; },
                dirname: function(p) {
                    var n = this.normalize(p);
                    if (n === '/') return '/';
                    if (n.endsWith('/')) n = n.substring(0, n.length - 1);
                    var idx = n.lastIndexOf('/');
                    if (idx === -1) return '.';
                    if (idx === 0) return '/';
                    return n.substring(0, idx);
                },
                basename: function(p) {
                    var n = this.normalize(p);
                    if (n === '/') return '';
                    if (n.endsWith('/')) n = n.substring(0, n.length - 1);
                    return n.substring(n.lastIndexOf('/') + 1);
                },
                extname: function(p) {
                    var base = this.basename(p);
                    var idx = base.lastIndexOf('.');
                    if (idx <= 0) return '';
                    return base.substring(idx);
                },
                parse: function(p) {
                    var ext = this.extname(p);
                    var base = this.basename(p);
                    var name = base.substring(0, base.length - ext.length);
                    var dir = this.dirname(p);
                    return { root: '', dir: dir, base: base, ext: ext, name: name };
                },
                sep: '/'
            };

            var mockGreenworks = {
                init: function() { return true; },
                initAPI: function() { return true; },
                on: function() {},
                getSteamId: function() { return { getRawSteamID: function() { return "76561198000000000"; }, getAccountID: function() { return 10000; }, accountId: 10000, steamId: "76561198000000000", getPersonaName: function() { return "Player"; }, getNickName: function() { return "Player"; } }; },
                getCurrentGameLanguage: function() { return "schinese"; },
                isCloudEnabled: function() { return false; },
                isCloudEnabledForUser: function() { return false; },
                getAchievementNames: function() { return []; },
                isSteamRunning: function() { return true; },
                getAppId: function() { return 1429560; },
                isDLCInstalled: function(id) { return true; },
                installDLC: function(id) { return true; },
                isSubscribedApp: function(id) { return true; },
                activateAchievement: function() {},
                saveTextToFile: function(f, c, cb) { if (cb) cb(); },
                readTextFromFile: function(f, cb) { if (cb) cb(""); },
                isSteamInBigPictureMode: function() { return false; }
            };

            window.require = function(mod) {
                if (mod === 'nw.gui' || mod === 'nw') return window.nw;
                if (mod === 'fs') return mockFs;
                if (mod === 'path') return mockPath;
                if (typeof mod === 'string' && mod.indexOf('greenworks') >= 0) return mockGreenworks;
                if (mod === 'electron') {
                    return {
                        ipcRenderer: {
                            send: function() {},
                            on: function() {},
                            sendSync: function() { return null; }
                        },
                        remote: {
                            getCurrentWindow: function() {
                                return {
                                    setFullScreen: function() {},
                                    isFullScreen: function() { return false; },
                                    close: function() {},
                                    minimize: function() {}
                                };
                            }
                        }
                    };
                }
                if (mod === 'os') {
                    return {
                        platform: function() { return 'win32'; },
                        homedir: function() { return ''; },
                        tmpdir: function() { return '/tmp'; }
                    };
                }
                return {};
            };

            // 5. 重构 Graphics 鼠标精准映射与首帧即时居中缩放自适应
            var hookInterval = setInterval(function() {
                if (window.Graphics) {
                    clearInterval(hookInterval);
                    Graphics._stretchEnabled = true;

                    Graphics.pageToCanvasX = function(x) {
                        if (this._canvas) {
                            var rect = this._canvas.getBoundingClientRect();
                            var scaleX = this._canvas.width / rect.width;
                            return Math.round((x - rect.left) * scaleX);
                        }
                        return 0;
                    };

                    Graphics.pageToCanvasY = function(y) {
                        if (this._canvas) {
                            var rect = this._canvas.getBoundingClientRect();
                            var scaleY = this._canvas.height / rect.height;
                            return Math.round((y - rect.top) * scaleY);
                        }
                        return 0;
                    };

                    Graphics.isInsideCanvas = function(x, y) {
                        return (x >= 0 && x < this._width && y >= 0 && y < this._height);
                    };

                    Graphics._updateRealScale = function() {
                        if (this._canvas) {
                            var w = this._width || 1920;
                            var h = this._height || 1080;
                            var winW = window.innerWidth || document.documentElement.clientWidth || 1280;
                            var winH = window.innerHeight || document.documentElement.clientHeight || 800;
                            var scale = Math.min(winW / w, winH / h);
                            if (scale <= 0 || isNaN(scale)) scale = 1;
                            this._realScale = scale;
                            this._canvas.style.width = Math.round(w * scale) + 'px';
                            this._canvas.style.height = Math.round(h * scale) + 'px';
                            this._canvas.style.position = 'absolute';
                            this._canvas.style.left = '0';
                            this._canvas.style.right = '0';
                            this._canvas.style.top = '0';
                            this._canvas.style.bottom = '0';
                            this._canvas.style.margin = 'auto';
                        }
                    };

                    Graphics._centerElement = function(element) {
                        this._updateRealScale();
                    };

                    Graphics._updateCanvas = function() {
                        this._canvas.width = this._width;
                        this._canvas.height = this._height;
                        this._canvas.style.zIndex = 1;
                        this._updateRealScale();
                    };

                    document.body.style.margin = '0';
                    document.body.style.padding = '0';
                    document.body.style.overflow = 'hidden';
                    document.body.style.backgroundColor = '#000000';

                    window.addEventListener('resize', function() {
                        Graphics._updateRealScale();
                    });

                    // 持续帧守护：确保游戏初始化后首帧即 100% 居中缩放自适应
                    var frameGuardCount = 0;
                    var frameGuard = setInterval(function() {
                        if (window.Graphics) {
                            Graphics._updateRealScale();
                            frameGuardCount++;
                            if (frameGuardCount > 60) clearInterval(frameGuard);
                        }
                    }, 50);
                }
            }, 20);

            // 6. 核心解密安全容错、彻底消除 Header is wrong 崩溃、全自动直通中文
            var engineFixInterval = setInterval(function() {
                if (window.Graphics && !Graphics._fontHooked) {
                    Graphics._fontHooked = true;
                    Graphics.isFontLoaded = function() { return true; };
                }

                if (window.Decrypter && !Decrypter._deckHooked) {
                    Decrypter._deckHooked = true;
                    Decrypter.readEncryptionkey = function() {
                        var key = (window.$dataSystem && window.$dataSystem.encryptionKey) ? window.$dataSystem.encryptionKey : 'd41d8cd98f00b204e9800998ecf8427e';
                        this._encryptionKey = key.split(/(.{2})/).filter(Boolean);
                    };

                    Decrypter.decryptArrayBuffer = function(arrayBuffer) {
                        if (!arrayBuffer || arrayBuffer.byteLength < Decrypter._headerlength) return arrayBuffer;
                        var header = new Uint8Array(arrayBuffer, 0, Decrypter._headerlength);

                        var i;
                        var ref = this.SIGNATURE + this.VER + this.REMAIN;
                        var refBytes = new Uint8Array(16);
                        for (i = 0; i < Decrypter._headerlength; i++) {
                            refBytes[i] = parseInt("0x" + ref.substr(i * 2, 2), 16);
                        }
                        var isEncrypted = true;
                        for (i = 0; i < Decrypter._headerlength; i++) {
                            if (header[i] !== refBytes[i]) {
                                isEncrypted = false;
                                break;
                            }
                        }
                        if (!isEncrypted) {
                            return arrayBuffer;
                        }

                        arrayBuffer = this.cutArrayHeader(arrayBuffer, Decrypter._headerlength);
                        var view = new DataView(arrayBuffer);
                        this.readEncryptionkey();
                        if (arrayBuffer && Decrypter._encryptionKey) {
                            var byteArray = new Uint8Array(arrayBuffer);
                            for (i = 0; i < Decrypter._headerlength && i < byteArray.length; i++) {
                                byteArray[i] = byteArray[i] ^ parseInt(Decrypter._encryptionKey[i], 16);
                                view.setUint8(i, byteArray[i]);
                            }
                        }

                        return arrayBuffer;
                    };
                }

                if (window.ConfigManager) {
                    ConfigManager.language = 0;
                }

                if (window.Scene_Boot && !Scene_Boot._deckHooked) {
                    Scene_Boot._deckHooked = true;
                    Scene_Boot.prototype.isGameFontLoaded = function() {
                        return true;
                    };
                }


            }, 20);

            // 7. 动态加载各游戏专属的适配补丁 (如 Spine 修复、PIXI NPOT 修复等)
            var _patchPathParts = window.location.pathname.split('/');
            var _patchGameId = (_patchPathParts.length >= 3 && _patchPathParts[1] === 'game') ? decodeURIComponent(_patchPathParts[2]) : '';
            if (_patchGameId) {
                var _xhrPatch = new XMLHttpRequest();
                _xhrPatch.open('GET', '/api/patch/' + encodeURIComponent(_patchGameId) + '.js?t=' + Date.now(), false);
                try {
                    _xhrPatch.send();
                    if (_xhrPatch.status === 200 && _xhrPatch.responseText) {
                        try {
                            eval(_xhrPatch.responseText);
                        } catch(e) {
                            console.error('[RPGWeb-Deck] 专属补丁执行失败 (' + _patchGameId + '):', e);
                        }
                    }
                } catch(e) {}
                
                // Add global XHR interceptor to bypass aggressive browser caching for local game assets
                var _orig_xhr_open = XMLHttpRequest.prototype.open;
                XMLHttpRequest.prototype.open = function(method, url, async, user, password) {
                    var args = Array.prototype.slice.call(arguments);
                    if (typeof url === 'string') {
                        if (url.indexOf('.rpgmvp') !== -1 || url.indexOf('.png') !== -1 || url.indexOf('.rpgmvo') !== -1 || url.indexOf('.m4a') !== -1 || url.indexOf('.json') !== -1) {
                            if (url.indexOf('?t=') === -1) {
                                url += (url.indexOf('?') === -1 ? '?' : '&') + 't=' + Date.now();
                            }
                        }
                        if (url.startsWith('data/')) {
                            url = window.location.pathname.replace('/index.html', '/') + url;
                        }
                        args[1] = url;
                    }
                    return _orig_xhr_open.apply(this, args);
                };

            }

            // 8. 零卡顿异步 Direct FS 存档直通引擎
            var checkInterval = setInterval(function() {
                if (window.StorageManager && window.LZString && !window.StorageManager.loadZip) {
                    clearInterval(checkInterval);
                    
                    var pathParts = window.location.pathname.split('/');
                    var gameId = (pathParts.length >= 3 && pathParts[1] === 'game') ? decodeURIComponent(pathParts[2]) : '';
                    if (!gameId) return;

                    var localSaveCache = {};

                    StorageManager.isLocalMode = function() {
                        return true;
                    };

                    StorageManager.localFileExists = function(savefileId) {
                        var name = (savefileId < 0) ? 'config.rpgsave' : (savefileId === 0) ? 'global.rpgsave' : ('file' + savefileId + '.rpgsave');
                        if (name in localSaveCache) {
                            return localSaveCache[name];
                        }
                        var xhr = new XMLHttpRequest();
                        xhr.open('HEAD', '/save/' + encodeURIComponent(gameId) + '/' + name + '?t=' + Date.now(), false);
                        try {
                            xhr.send();
                            var exists = (xhr.status === 200);
                            localSaveCache[name] = exists;
                            return exists;
                        } catch(e) {
                            return false;
                        }
                    };

                    StorageManager.loadFromLocalFile = function(savefileId) {
                        var name = (savefileId < 0) ? 'config.rpgsave' : (savefileId === 0) ? 'global.rpgsave' : ('file' + savefileId + '.rpgsave');
                        var xhr = new XMLHttpRequest();
                        xhr.open('GET', '/save/' + encodeURIComponent(gameId) + '/' + name + '?t=' + Date.now(), false);
                        try {
                            xhr.send();
                            if (xhr.status === 200) {
                                localSaveCache[name] = true;
                                return LZString.decompressFromBase64(xhr.responseText);
                            }
                        } catch(e) {
                            console.error('[RPGWeb-Deck] 读档异常:', e);
                        }
                        return null;
                    };

                    StorageManager.saveToLocalFile = function(savefileId, json) {
                        var name = (savefileId < 0) ? 'config.rpgsave' : (savefileId === 0) ? 'global.rpgsave' : ('file' + savefileId + '.rpgsave');
                        localSaveCache[name] = true;
                        
                        var compressed = LZString.compressToBase64(json);
                        fetch('/api/save/' + encodeURIComponent(gameId) + '?file=' + name, {
                            method: 'POST',
                            headers: { 'Content-Type': 'text/plain' },
                            body: compressed
                        }).catch(function(err) {
                            console.error('[RPGWeb-Deck] 异步存档异常:', err);
                        });
                    };
                    if (window.Graphics) {
                        var _orig_printLoadingError = Graphics.printLoadingError;
                        Graphics.printLoadingError = function(url) {
                            console.error("[RPGWeb-Deck] Graphics.printLoadingError triggered for URL: " + url);
                            if (_orig_printLoadingError) {
                                _orig_printLoadingError.apply(this, arguments);
                            }
                        };
                    }
                }
            }, 20);
        })();
