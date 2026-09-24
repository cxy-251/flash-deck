// 本机原生播放桥接（见 native_player.py）：omniBridge 只在本机嵌入的 QWebEngineView
// 里才存在（局域网/远程浏览器没有 qt.webChannelTransport），据此判断走原生解码还是
// 网页内置的 <video>/<audio>。nativePlaybackKind 记录原生播放器当前在播"短视频"还是
// "音频"，上一条/下一条/删除从 Python 转发回来时（见文件末尾 window.nativePlayerNext
// 等函数）靠这个分流。
let nativePlaybackKind = null;

// 本机原生播放器（native_player.py 里那个悬浮控件）上一条/下一条/删除按钮被点了，
// Python 转发回网页调这几个函数——原生播放器自己不维护列表，这边算出"下一条该放
// 哪个文件"之后，直接复用已有的短视频翻页/删除逻辑（那几个函数内部会再走一遍
// openShortVideoPlayer，本机情况下会再次命中上面的 omniBridge 分支，重新喊 Python 播）。
// 音频这条目前还没接原生播放（见 hub.js 内的 playAudioItem，仍然是网页 <audio> 播放），
// 所以 nativePlaybackKind 目前只会是 'shortvideo'。
function nativePlayerNext() {
    if (nativePlaybackKind === 'shortvideo') playShortVideoDelta(1);
    else if (nativePlaybackKind === 'audio') playNextAudio();
}

function nativePlayerPrev() {
    if (nativePlaybackKind === 'shortvideo') playShortVideoDelta(-1);
    else if (nativePlaybackKind === 'audio') playPrevAudio();
}

function nativePlayerDelete() {
    if (nativePlaybackKind === 'shortvideo') deleteShortVideoFromPlayer();
    else if (nativePlaybackKind === 'audio' && currentAudioItem) {
        deleteAudioFile(currentAudioItem.rel_path || currentAudioItem.filename, !!currentAudioItem.is_nsfw);
    }
}

function nativePlayerToggleLike(liked) {
    if (nativePlaybackKind === 'shortvideo') toggleShortVideoLikeFromPlayer();
}

window.nativePlayerNext = nativePlayerNext;

window.nativePlayerPrev = nativePlayerPrev;

window.nativePlayerDelete = nativePlayerDelete;

window.nativePlayerToggleLike = nativePlayerToggleLike;
