// Live Empire (直播帝国) Specific Adapter Patch

(function() {
    console.log("[RPG-Deck] Loading live-empire adapter patches...");

    // 1. 修复游戏误打包的 Axure 原型脚本报错
    window.$axure = {
        loadDocument: function() {}
    };

    // 2. 模拟 Steam 登录验证，彻底绕过 Steam 客户端登录检测
    window.testSteamAPI = function() {
        console.log("[RPG-Deck] 模拟 Steam 登录成功");
        window.steamId = "76561198000000000";
        return true;
    };
    window.steamLogin = function() {
        window.steamId = "76561198000000000";
        return true;
    };

    // 3. 拦截 Main.prototype.createChildren，安全跳过开场 MP4 视频，直接载入白鹭资源与主题 (runGame)
    var checkMainInterval = setInterval(function() {
        if (window.Main && window.Main.prototype) {
            clearInterval(checkMainInterval);
            console.log("[RPG-Deck] Hooking Main.prototype for live-empire...");

            window.Main.prototype.createChildren = function() {
                var self = this;
                var e = new window.AssetAdapter();
                egret.registerImplementation("eui.IAssetAdapter", e);
                egret.registerImplementation("eui.IThemeAdapter", new window.ThemeAdapter());

                console.log("[RPG-Deck] 正在安全启动白鹭引擎核心资源 (runGame)...");
                this.runGame().catch(function(err) {
                    console.error("[RPG-Deck] runGame 执行失败:", err);
                });
            };
        }
    }, 5);
})();
