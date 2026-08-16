// Live Empire (直播帝国) Specific Adapter Patch

(function() {
    console.log("[RPG-Deck] Loading live-empire adapter patches...");

    // 1. 修复游戏误打包的 Axure 原型脚本报错
    window.$axure = {
        loadDocument: function() {}
    };

    // 2. 修复游戏启动视频加载失败时，开发者的回退逻辑未正确执行 runGame() 的严重 Bug
    var checkMainInterval = setInterval(function() {
        if (window.Main && window.Main.prototype) {
            clearInterval(checkMainInterval);
            console.log("[RPG-Deck] Hooking Main.prototype.onLoadErr for live-empire...");
            
            var origOnLoadErr = window.Main.prototype.onLoadErr;
            window.Main.prototype.onLoadErr = function() {
                console.log("[RPG-Deck] 拦截到启动视频加载失败，正在自动安全跳过并加载游戏资源 (runGame)...");
                if (this.vd) {
                    try {
                        this.vd.close();
                        this.removeChild(this.vd);
                    } catch(e) {}
                    this.vd = null;
                }
                var self = this;
                if (typeof this.runGame === 'function') {
                    this.runGame().catch(function(err) {
                        console.error("[RPG-Deck] runGame 执行失败:", err);
                    });
                } else if (origOnLoadErr) {
                    origOnLoadErr.apply(self, arguments);
                }
            };
        }
    }, 10);
})();
