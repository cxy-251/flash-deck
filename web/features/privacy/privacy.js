let nsfwModalView = 'unlock'; // 'unlock' | 'unlocked' | 'change'

function updateNsfwUI() {
    const gameBtn = document.getElementById('game-nsfw-lock-btn');
    const gameIcon = document.getElementById('game-nsfw-lock-icon');
    const gameText = document.getElementById('game-nsfw-lock-text');

    if (isNsfwUnlocked) {
        const initStyle = document.getElementById('nsfw-init-style');
        if (initStyle) initStyle.remove();   // 首次解锁：拿掉 <head> 里那份防闪烁用的早期隐藏样式

        const btnLabel = isDeckLocal ? '实体机已解锁' : '隐私已解锁';
        if (gameIcon) gameIcon.textContent = '🔓';
        if (gameText) gameText.textContent = btnLabel;
        if (gameBtn) {
            gameBtn.classList.add('active');
            gameBtn.title = isDeckLocal ? 'Steam Deck 实体机免密完全放行' : '当前设备已授权解锁 NSFW 专区';
        }
    } else {
        if (gameIcon) gameIcon.textContent = '🔒';
        if (gameText) gameText.textContent = '隐私锁定';
        if (gameBtn) {
            gameBtn.classList.remove('active');
            gameBtn.title = 'NSFW 专区已锁定并隐形，点击输入密码解锁';
        }
    }
    // 展示/隐藏 + "正停留在刚变得不可见的分区" 的退避逻辑，统一交给权限表处理
    // （见 ACCESS_RULES/applyAccessRules，覆盖 rpg/slg/manga/novels/audio 等所有解锁态受控入口）。
    if (typeof applyAccessRules === 'function') applyAccessRules();
}

function checkNsfwStatus() {
    return fetch('/api/auth/status?t=' + Date.now())
        .then(r => r.json())
        .then(status => {
            if (status) {
                isDeckLocal = !!status.is_local;
                const prev = isNsfwUnlocked;
                isNsfwUnlocked = !!status.unlocked;
                try { 
                    localStorage.setItem('omni_nsfw_unlocked', isNsfwUnlocked ? '1' : '0');
                    sessionStorage.setItem('omni_nsfw_unlocked', isNsfwUnlocked ? '1' : '0'); 
                } catch(e) {}
                updateNsfwUI();
                if ((isNsfwUnlocked !== prev) || (!prev && isNsfwUnlocked) || (typeof allGames !== 'undefined' && allGames.length > 0)) {
                    if (typeof applyFilter === 'function') {
                        applyFilter();
                    }
                }
            }
            return status;
        })
        .catch(() => {});
}

function openNsfwModal() {
    const modal = document.getElementById('nsfw-lock-modal');
    if (!modal) return;
    modal.style.display = 'flex';

    if (isNsfwUnlocked) {
        switchNsfwModalView('unlocked');
    } else {
        switchNsfwModalView('unlock');
    }
}

function closeNsfwModal() {
    const modal = document.getElementById('nsfw-lock-modal');
    if (modal) modal.style.display = 'none';
    const pwdInput = document.getElementById('nsfw-password-input');
    if (pwdInput) pwdInput.value = '';
    const oldPwd = document.getElementById('nsfw-old-pwd-input');
    if (oldPwd) oldPwd.value = '';
    const newPwd = document.getElementById('nsfw-new-pwd-input');
    if (newPwd) newPwd.value = '';
    hideNsfwMsgs();
}

function hideNsfwMsgs() {
    ['nsfw-unlock-msg', 'nsfw-unlocked-msg', 'nsfw-change-msg'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.style.display = 'none'; el.textContent = ''; }
    });
}

function switchNsfwModalView(view) {
    hideNsfwMsgs();
    const vUnlock = document.getElementById('nsfw-view-unlock');
    const vUnlocked = document.getElementById('nsfw-view-unlocked');
    const vChange = document.getElementById('nsfw-view-change');
    const titleEl = document.getElementById('nsfw-modal-title');
    const iconEl = document.getElementById('nsfw-modal-icon');
    const btnBack = document.getElementById('nsfw-btn-back');
    const btnCancel = document.getElementById('nsfw-btn-cancel');
    const btnAction = document.getElementById('nsfw-btn-action');

    if (view === 'back') {
        view = isNsfwUnlocked ? 'unlocked' : 'unlock';
    }
    nsfwModalView = view;

    if (view === 'unlock') {
        if (vUnlock) vUnlock.style.display = 'block';
        if (vUnlocked) vUnlocked.style.display = 'none';
        if (vChange) vChange.style.display = 'none';
        if (titleEl) titleEl.textContent = 'NSFW 隐私安全验证';
        if (iconEl) iconEl.textContent = '🔐';
        if (btnBack) btnBack.style.display = 'none';
        if (btnCancel) btnCancel.style.display = 'inline-flex';
        if (btnAction) {
            btnAction.style.display = 'inline-flex';
            btnAction.textContent = '立即解锁';
            btnAction.style.background = '#238636';
            btnAction.style.borderColor = '#2ea043';
            btnAction.onclick = submitNsfwUnlock;
        }
        setTimeout(() => {
            const p = document.getElementById('nsfw-password-input');
            if (p) p.focus();
        }, 100);
    } else if (view === 'unlocked') {
        if (vUnlock) vUnlock.style.display = 'none';
        if (vUnlocked) vUnlocked.style.display = 'block';
        if (vChange) vChange.style.display = 'none';
        if (titleEl) titleEl.textContent = 'NSFW 隐私状态管理';
        if (iconEl) iconEl.textContent = '🔓';
        if (btnBack) btnBack.style.display = 'none';
        if (btnCancel) btnCancel.style.display = 'none';
        if (btnAction) {
            if (isDeckLocal) {
                btnAction.style.display = 'none';
            } else {
                btnAction.style.display = 'inline-flex';
                btnAction.textContent = '🔒 重新上锁 (隐形)';
                btnAction.style.background = '#da3633';
                btnAction.style.borderColor = '#f85149';
                btnAction.onclick = submitNsfwLock;
            }
        }
        const descEl = document.getElementById('nsfw-unlocked-desc');
        if (descEl) {
            descEl.textContent = isDeckLocal
                ? '当前处于 Steam Deck 实体机环境，默认免密完全放行。局域网/广域网访客需输入密码方可解锁。'
                : '敏感专区（RPG Maker、SLG、漫画、小说、音声）已全部展示。如需离开或避免他人借用设备，可随时在此重新上锁。';
        }
    } else if (view === 'change') {
        if (vUnlock) vUnlock.style.display = 'none';
        if (vUnlocked) vUnlocked.style.display = 'none';
        if (vChange) vChange.style.display = 'block';
        if (titleEl) titleEl.textContent = '修改全局访问密码';
        if (iconEl) iconEl.textContent = '🔑';
        if (btnBack) btnBack.style.display = 'inline-flex';
        if (btnCancel) btnCancel.style.display = 'none';
        if (btnAction) {
            btnAction.style.display = 'inline-flex';
            btnAction.textContent = '保存新密码';
            btnAction.style.background = '#1f6feb';
            btnAction.style.borderColor = '#388bfd';
            btnAction.onclick = submitNsfwChangePassword;
        }
        setTimeout(() => {
            const p = document.getElementById('nsfw-old-pwd-input');
            if (p) p.focus();
        }, 100);
    }
}

function submitNsfwUnlock() {
    const pwdInput = document.getElementById('nsfw-password-input');
    const chkRemember = document.getElementById('nsfw-remember-checkbox');
    const msgEl = document.getElementById('nsfw-unlock-msg');
    const pwd = (pwdInput ? pwdInput.value : '').trim();
    const remember = chkRemember ? chkRemember.checked : true;

    if (!pwd) {
        if (msgEl) {
            msgEl.style.display = 'block';
            msgEl.style.color = '#f85149';
            msgEl.textContent = '请输入访问密码';
        }
        return;
    }

    fetch('/api/auth/unlock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pwd, remember: remember })
    })
    .then(r => r.json())
    .then(res => {
        if (res.success && res.token) {
            localStorage.setItem('omni_nsfw_token', res.token);
            isNsfwUnlocked = true;
            updateNsfwUI();
            closeNsfwModal();
            try {
                localStorage.removeItem('omni_games_cache');
                sessionStorage.removeItem('omni_games_cache');
            } catch(e) {}
            loadGames();
            if (typeof activePrimarySection !== 'undefined' && activePrimarySection === 'media') {
                prewarmMediaLibraries();
                Omni.call(activeMediaTab, 'onUnlock');
            }
            if (typeof showMegaToast === 'function') {
                showMegaToast('✅ 已成功解锁 NSFW 隐私专区！');
            }
        } else {
            if (msgEl) {
                msgEl.style.display = 'block';
                msgEl.style.color = '#f85149';
                msgEl.textContent = res.error || '密码错误，请重试';
            }
        }
    })
    .catch(err => {
        if (msgEl) {
            msgEl.style.display = 'block';
            msgEl.style.color = '#f85149';
            msgEl.textContent = '网络请求失败，请稍后重试';
        }
    });
}

function submitNsfwLock() {
    fetch('/api/auth/lock', { method: 'POST' })
        .finally(() => {
            localStorage.removeItem('omni_nsfw_token');
            try {
                localStorage.removeItem('omni_games_cache');
                sessionStorage.removeItem('omni_games_cache');
            } catch(e) {}
            isNsfwUnlocked = false;
            updateNsfwUI();
            closeNsfwModal();
            loadGames();
            if (typeof showMegaToast === 'function') {
                showMegaToast('🔒 NSFW 专区已重新锁定并隐形');
            }
        });
}

function submitNsfwChangePassword() {
    const oldPwd = document.getElementById('nsfw-old-pwd-input').value;
    const newPwd = document.getElementById('nsfw-new-pwd-input').value;
    const msgEl = document.getElementById('nsfw-change-msg');

    if (!newPwd || newPwd.length < 4) {
        if (msgEl) {
            msgEl.style.display = 'block';
            msgEl.style.color = '#f85149';
            msgEl.textContent = '新密码长度至少需要 4 位字符';
        }
        return;
    }

    fetch('/api/auth/change_password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: oldPwd, new_password: newPwd })
    })
    .then(r => r.json())
    .then(res => {
        if (res.success) {
            if (msgEl) {
                msgEl.style.display = 'block';
                msgEl.style.color = '#3fb950';
                msgEl.textContent = '✅ 密码修改成功！';
            }
            if (typeof showMegaToast === 'function') {
                showMegaToast('✅ 访问密码修改成功！');
            }
            setTimeout(() => {
                switchNsfwModalView(isNsfwUnlocked ? 'unlocked' : 'unlock');
            }, 1200);
        } else {
            if (msgEl) {
                msgEl.style.display = 'block';
                msgEl.style.color = '#f85149';
                msgEl.textContent = res.error || '原密码错误，修改失败';
            }
        }
    })
    .catch(err => {
        if (msgEl) {
            msgEl.style.display = 'block';
            msgEl.style.color = '#f85149';
            msgEl.textContent = '网络请求失败，请稍后重试';
        }
    });
}

function submitNsfwAction() {
    if (nsfwModalView === 'unlock') {
        submitNsfwUnlock();
    } else if (nsfwModalView === 'unlocked') {
        submitNsfwLock();
    } else if (nsfwModalView === 'change') {
        submitNsfwChangePassword();
    }
}
