// Succubus Boss Specific Patches

(function() {
    console.log("[RPG-Deck] Loading succubus-boss specific patches...");

    // 1. Fix PIXI.js NPOT (Non-Power-Of-Two) Texture GL errors
    var _pixiCheckInterval = setInterval(function() {
        if (window.PIXI && window.PIXI.settings) {
            clearInterval(_pixiCheckInterval);
            console.log("[RPG-Deck] Applying PIXI NPOT workaround for succubus-boss");
            window.PIXI.settings.MIPMAP_TEXTURES = false;
            window.PIXI.settings.WRAP_MODE = window.PIXI.WRAP_MODES ? window.PIXI.WRAP_MODES.CLAMP : 0;
            if (window.PIXI.glCore && window.PIXI.glCore.GLTexture) {
                var _origUpload = window.PIXI.glCore.GLTexture.prototype.upload;
                window.PIXI.glCore.GLTexture.prototype.upload = function(source) {
                    this.mipmap = false;
                    this.wrapMode = 33071; // gl.CLAMP_TO_EDGE
                    return _origUpload.apply(this, arguments);
                };
            }
        }
    }, 50);

    // 2. 原生 ChimakiSpine 驱动引擎
    var spineCache = {};
    var activeSpines = {};

    var DEFAULT_POSITIONS = {
        'debby': { x: 960, y: 2030, sx: 0.6, sy: 0.6 },
        'kurama': { x: 960, y: 2030, sx: 0.6, sy: 0.6 },
        'olivia': { x: 960, y: 2030, sx: 0.6, sy: 0.6 },
        'zelda': { x: 960, y: 1930, sx: 0.6, sy: 0.6 },
        'nadia': { x: 960, y: 2000, sx: 0.6, sy: 0.6 },
        'alica': { x: 960, y: 2130, sx: 0.6, sy: 0.6 },
        'orc': { x: -100, y: -300, sx: 1.1, sy: 1.1 }
    };

    function getDefaultPos(name) {
        var lower = (name || '').toLowerCase();
        if (DEFAULT_POSITIONS[lower]) return DEFAULT_POSITIONS[lower];
        return { x: 0, y: 1080, sx: 1.0, sy: 1.0 };
    }

    function getSpineContainer() {
        if (!window.SceneManager || !SceneManager._scene) return null;
        var scene = SceneManager._scene;
        if (scene._spriteset) {
            if (!scene._spriteset._spineContainer || scene._spriteset._spineContainer._destroyed) {
                scene._spriteset._spineContainer = new PIXI.Container();
                scene._spriteset._spineContainer.name = "SpineCharacterLayer";
                if (scene._spriteset._pictureContainer && scene._spriteset._pictureContainer.parent === scene._spriteset) {
                    try {
                        var pIdx = scene._spriteset.getChildIndex(scene._spriteset._pictureContainer);
                        scene._spriteset.addChildAt(scene._spriteset._spineContainer, pIdx);
                    } catch (e) {
                        scene._spriteset.addChild(scene._spriteset._spineContainer);
                    }
                } else {
                    scene._spriteset.addChild(scene._spriteset._spineContainer);
                }
            }
            return scene._spriteset._spineContainer;
        }
        if (!scene._spineContainer || scene._spineContainer._destroyed) {
            scene._spineContainer = new PIXI.Container();
            scene._spineContainer.name = "SpineFallbackLayer";
            if (scene._windowLayer && scene._windowLayer.parent === scene) {
                try {
                    scene.addChildAt(scene._spineContainer, scene.getChildIndex(scene._windowLayer));
                } catch (e) {
                    scene.addChild(scene._spineContainer);
                }
            } else {
                scene.addChild(scene._spineContainer);
            }
        }
        return scene._spineContainer;
    }

    function getSkeletonData(name) {
        if (spineCache[name]) return spineCache[name];
        var basePath = 'img/spine/' + name + '/' + name;
        var atlasUrl = basePath + '.atlas';
        var jsonUrl = basePath + '.json';
        var rpgUrl = basePath + '.rpgmvp';
        var pngUrl = basePath + '.png';

        var xhrAtlas = new XMLHttpRequest();
        xhrAtlas.open('GET', atlasUrl, false);
        try { xhrAtlas.send(); } catch(e) { return null; }
        if (xhrAtlas.status !== 200) return null;
        var atlasText = xhrAtlas.responseText;

        var xhrJson = new XMLHttpRequest();
        xhrJson.open('GET', jsonUrl, false);
        try { xhrJson.send(); } catch(e) { return null; }
        if (xhrJson.status !== 200) return null;
        var jsonData = JSON.parse(xhrJson.responseText);

        try {
            var textureAtlas = new PIXI.spine.core.TextureAtlas(atlasText, function(line, cb) {
                var pagePngUrl = basePath.substring(0, basePath.lastIndexOf('/') + 1) + line;
                if (!pagePngUrl.endsWith('.png')) {
                    pagePngUrl += '.png';
                }
                var pageRpgUrl = pagePngUrl.replace('.png', '.rpgmvp');
                var pageImgUrl = pagePngUrl;
                
                var xhrCheck = new XMLHttpRequest();
                xhrCheck.open('HEAD', pageRpgUrl + '?t=' + Date.now(), false);
                try { xhrCheck.send(); } catch(e) {}
                
                if (xhrCheck.status === 200) {
                    var xhrDec = new XMLHttpRequest();
                    xhrDec.open('GET', pageRpgUrl, false);
                    xhrDec.overrideMimeType('text/plain; charset=x-user-defined');
                    try {
                        xhrDec.send();
                        if (xhrDec.status === 200 && window.Decrypter) {
                            var str = xhrDec.responseText;
                            var bytes = new Uint8Array(str.length);
                            for (var i = 0; i < str.length; i++) {
                                bytes[i] = str.charCodeAt(i) & 0xff;
                            }
                            if (!Decrypter._encryptionKey) {
                                var key = (window.$dataSystem && $dataSystem.encryptionKey) ? $dataSystem.encryptionKey : 'd41d8cd98f00b204e9800998ecf8427e';
                                Decrypter._encryptionKey = key.split(/(.{2})/).filter(Boolean);
                            }
                            var dec = Decrypter.decryptArrayBuffer(bytes.buffer);
                            pageImgUrl = Decrypter.createBlobUrl(dec);
                        }
                    } catch(err) {}
                }
                
                var baseTex = PIXI.BaseTexture.fromImage(pageImgUrl);
                cb(baseTex);
            });
            var atlasLoader = new PIXI.spine.core.AtlasAttachmentLoader(textureAtlas);
            var skeletonJson = new PIXI.spine.core.SkeletonJson(atlasLoader);
            var skeletonData = skeletonJson.readSkeletonData(jsonData);

            spineCache[name] = skeletonData;
            return skeletonData;
        } catch(e) {
            return null;
        }
    }

    window.ChimakiSpine = {
        _activeSpines: activeSpines,
        load: function(name, slotId) {
            slotId = slotId || 1;
            if (activeSpines[name]) return activeSpines[name];

            var data = getSkeletonData(name);
            if (!data) return null;
            var container = getSpineContainer();
            if (!container) return null;

            var spine = new PIXI.spine.Spine(data);
            spine.name = name;
            spine.slotId = slotId;

            var defPos = getDefaultPos(name);
            spine.position.set(defPos.x, defPos.y);
            spine.scale.set(defPos.sx, defPos.sy);
            spine.visible = false;

            try {
                if (data.animations && data.animations.length > 0) {
                    spine.state.setAnimation(0, data.animations[0].name, true);
                }
            } catch(e) {}

            container.addChild(spine);
            activeSpines[name] = spine;
            return spine;
        },
        set: function(name, x, y, sx, sy) {
            var spine = activeSpines[name] || this.load(name, 1);
            if (spine) {
                spine.position.set(x, y);
                spine.scale.set(sx, (sy !== undefined) ? sy : sx);
                spine.visible = true;
            }
        },
        skin: function(name, skinName) {
            var spine = activeSpines[name] || this.load(name, 1);
            if (spine && skinName && spine.skeleton && spine.skeleton.data) {
                var skins = spine.skeleton.data.skins || [];
                var targetSkin = null;
                for (var i = 0; i < skins.length; i++) {
                    if (skins[i].name === skinName) { targetSkin = skins[i].name; break; }
                }
                if (!targetSkin) {
                    var lower = skinName.toLowerCase();
                    for (var j = 0; j < skins.length; j++) {
                        if (skins[j].name.toLowerCase() === lower) { targetSkin = skins[j].name; break; }
                    }
                }
                if (targetSkin) {
                    try {
                        spine.skeleton.setSkinByName(targetSkin);
                        for (var s = 0; s < spine.skeleton.slots.length; s++) {
                            var slot = spine.skeleton.slots[s];
                            var attachmentName = slot.data.attachmentName;
                            var attachment = null;
                            if (attachmentName) {
                                attachment = spine.skeleton.getAttachment(s, attachmentName);
                            }
                            slot.setAttachment(attachment);
                        }
                    } catch(e) {}
                }
                spine.visible = true;
            }
        },
        play: function(name, animName, loop) {
            var spine = activeSpines[name] || this.load(name, 1);
            if (spine && animName && spine.skeleton && spine.skeleton.data) {
                var anims = spine.skeleton.data.animations || [];
                var targetAnim = null;
                for (var i = 0; i < anims.length; i++) {
                    if (anims[i].name === animName) { targetAnim = anims[i].name; break; }
                }
                if (!targetAnim) {
                    var lower = animName.toLowerCase();
                    for (var j = 0; j < anims.length; j++) {
                        if (anims[j].name.toLowerCase() === lower) { targetAnim = anims[j].name; break; }
                    }
                }
                if (targetAnim) {
                    try {
                        spine.state.setAnimation(0, targetAnim, loop !== false);
                    } catch(e) {}
                }
                spine.visible = true;
            }
        },
        hide: function(name) {
            if (name && activeSpines[name]) {
                activeSpines[name].visible = false;
            } else if (!name) {
                Object.keys(activeSpines).forEach(function(k) {
                    if (activeSpines[k]) activeSpines[k].visible = false;
                });
            }
        },
        clear: function(name) {
            var container = getSpineContainer();
            if (!container) return;
            if (name && name !== 'all') {
                if (activeSpines[name]) {
                    try { container.removeChild(activeSpines[name]); } catch(e) {}
                    delete activeSpines[name];
                }
            } else {
                try { container.removeChildren(); } catch(e) {}
                activeSpines = {};
            }
        }
    };

    var hookSpineCmd = setInterval(function() {
        if (window.Game_Interpreter && !Game_Interpreter.prototype._chimakiHooked) {
            Game_Interpreter.prototype._chimakiHooked = true;
            clearInterval(hookSpineCmd);
            var _Game_Interpreter_pluginCommand = Game_Interpreter.prototype.pluginCommand;
            Game_Interpreter.prototype.pluginCommand = function(command, args) {
                _Game_Interpreter_pluginCommand.call(this, command, args);
                if (command === 'C_SPINE' && args.length > 0) {
                    var sub = args[0].toUpperCase();
                    var name = args[1];
                    if (sub === 'LOAD') {
                        var slot = (args[2] !== undefined) ? args[2] : 1;
                        ChimakiSpine.load(name, slot);
                    } else if (sub === 'SET') {
                        var x = (args[2] !== undefined) ? Number(args[2]) : 960;
                        var y = (args[3] !== undefined) ? Number(args[3]) : 1080;
                        var sx = (args[4] !== undefined) ? Number(args[4]) : 1.0;
                        // args[5] is probably transition time or opacity, not scaleY!
                        var sy = sx; 
                        ChimakiSpine.set(name, x, y, sx, sy);
                    } else if (sub === 'SKIN') {
                        ChimakiSpine.skin(name, args[2]);
                    } else if (sub === 'PLAY') {
                        ChimakiSpine.play(name, args[2], args[3] !== 'false');
                    } else if (sub === 'HIDE') {
                        ChimakiSpine.hide(name);
                    } else if (sub === 'CLEAR') {
                        ChimakiSpine.clear(name);
                    } else if (sub === 'CLOSE_SLOT_ATTR') {
                        var spine = activeSpines[name];
                        if (spine && args[3]) {
                            var slots = args[3].split(';');
                            for (var i = 0; i < slots.length; i++) {
                                var idx = parseInt(slots[i]);
                                if (!isNaN(idx) && spine.skeleton.slots[idx]) {
                                    spine.skeleton.slots[idx].setAttachment(null);
                                }
                            }
                        }
                    } else if (sub === 'RESET_SLOT_ATTR') {
                        var spine = activeSpines[name];
                        if (spine && args[3]) {
                            var slots = args[3].split(';');
                            for (var i = 0; i < slots.length; i++) {
                                var idx = parseInt(slots[i]);
                                if (!isNaN(idx) && spine.skeleton.slots[idx]) {
                                    spine.skeleton.slots[idx].setToSetupPose();
                                }
                            }
                        }
                    }
                }
            };
        }
    }, 20);

    var hookSceneManager = setInterval(function() {
        if (window.SceneManager && !SceneManager._spineHooked) {
            SceneManager._spineHooked = true;
            clearInterval(hookSceneManager);
            var _orig_SceneManager_changeScene = SceneManager.changeScene;
            SceneManager.changeScene = function() {
                if (this.isSceneChanging() && !this.isCurrentSceneBusy()) {
                    if (window.ChimakiSpine) {
                        ChimakiSpine.clear('all');
                    }
                }
                _orig_SceneManager_changeScene.call(this);
            };
        }
    }, 20);

    // 3. Scene and Game specific hooks
    var engineFixInterval = setInterval(function() {
        if (window.SceneManager && !SceneManager._deckHooked) {
            SceneManager._deckHooked = true;
            var _orig_SceneManager_goto = SceneManager.goto;
            SceneManager.goto = function(sceneClass) {
                if (sceneClass && (sceneClass.name === 'Scene_InitialLanguage' || (sceneClass.prototype && sceneClass.prototype.constructor && sceneClass.prototype.constructor.name === 'Scene_InitialLanguage'))) {
                    if (window.ConfigManager) ConfigManager.language = 0;
                    if (window.$gameSystem && $gameSystem.mulitLangSET) $gameSystem.mulitLangSET('繁中');
                    _orig_SceneManager_goto.call(this, Scene_Title);
                    return;
                }
                _orig_SceneManager_goto.call(this, sceneClass);
            };
        }

        if (window.Game_System && !Game_System._deckHooked) {
            Game_System._deckHooked = true;
            Game_System.prototype.initMessageFontSettings = function() {
                var loc = (window.$dataSystem && $dataSystem.locale) ? $dataSystem.locale : 'zh_CN';
                if (loc && loc.match && loc.match(/^zh/)) {
                    this._msgFontName = (window.Yanfly && Yanfly.Param) ? Yanfly.Param.MSGCNFontName : 'GameFont';
                } else if (loc && loc.match && loc.match(/^ko/)) {
                    this._msgFontName = (window.Yanfly && Yanfly.Param) ? Yanfly.Param.MSGKRFontName : 'GameFont';
                } else {
                    this._msgFontName = (window.Yanfly && Yanfly.Param) ? Yanfly.Param.MSGFontName : 'GameFont';
                }
                this._msgFontSize = (window.Yanfly && Yanfly.Param) ? Yanfly.Param.MSGFontSize : 28;
                this._msgFontOutline = (window.Yanfly && Yanfly.Param) ? Yanfly.Param.MSGFontOutline : 4;
            };
        }

        if (window.Scene_Map && !Scene_Map._deckHooked) {
            Scene_Map._deckHooked = true;
            clearInterval(engineFixInterval);

            var _Scene_Map_start = Scene_Map.prototype.start;
            Scene_Map.prototype.start = function() {
                _Scene_Map_start.call(this);
                if (this._fadeSprite) {
                    this._fadeSprite.opacity = 0;
                }
                if (window.$gameScreen) {
                    $gameScreen.startFadeIn(24);
                }
                if (window.Graphics && Graphics._fadeColor) {
                    Graphics._fadeColor[3] = 0;
                }
                this.startFadeIn(24, false);
            };

            var _Scene_Map_update = Scene_Map.prototype.update;
            Scene_Map.prototype.update = function() {
                _Scene_Map_update.call(this);
                if (this.isActive()) {
                    if (this._fadeSprite && this._fadeSprite.opacity > 0 && !this.isBusy()) {
                        this._fadeSprite.opacity = 0;
                    }
                    if (window.Graphics && Graphics._fadeColor && Graphics._fadeColor[3] > 0 && !this.isBusy()) {
                        Graphics._fadeColor[3] = 0;
                    }
                }
            };
        }
    }, 20);

})();
