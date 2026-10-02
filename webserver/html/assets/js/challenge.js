import {messageManager, apiClient} from './utils.js';

class ChallengePage {
    constructor() {
        this.challengeId = new URLSearchParams(window.location.search).get('id');
        if (!this.challengeId) {
            messageManager.showError('No challenge ID provided');
            return;
        }

        this.initElements();
        this.initAudio();
        this.loadChallengeData();
    }

    initElements() {
        this.loadingDiv = document.querySelector('.loading');
        this.challengeContent = document.querySelector('.challenge-content');
        this.leaderboardSection = document.querySelector('.leaderboard-section');
        this.loginRequiredBanner = document.querySelector('.login-required-banner');

        this.challengeTitle = document.getElementById('challenge-title');
        this.challengeDescription = document.getElementById('challenge-description');
        this.challengeImage = document.getElementById('challenge-image');
        this.challengeCategory = document.getElementById('challenge-category');
        this.challengeDifficulty = document.getElementById('challenge-difficulty');
        this.challengePoints = document.getElementById('challenge-points');
        this.challengeSolves = document.getElementById('challenge-solves');
        this.challengeStatus = document.getElementById('challenge-status');

        this.deployButton = document.getElementById('deploy-button');
        this.cancelButton = document.getElementById('cancel-button');
        this.extendTimeButton = document.getElementById('extend-time-button');

        this.challengeTimerContainer = document.querySelector('.challenge-timer-container');
        this.challengeTimerElement = document.getElementById('challenge-timer');
        this.timerElement = document.getElementById('timer');

        this.connectionInfo = document.getElementById('connection-info');
        this.subnetsContainer = document.getElementById('subnets-container');
        this.hintsContainer = document.getElementById('hints-container');

        this.flagInput = document.getElementById('flag-input');
        this.submitFlag = document.getElementById('submit-flag');
        this.flagFeedback = document.getElementById('flag-feedback');

        this.timerInterval = null;
        this.challengeTimerInterval = null;
        this.elapsedSeconds = 0;
        this.remainingSeconds = 0;

        this.leaderboardContainer = document.getElementById('leaderboard-content');
    }

    initAudio() {
        this.achievementSound = new Audio('../assets/sounds/achievement.mp3');
        this.completionSound = new Audio('../assets/sounds/completion.mp3');
        window.addEventListener('load', () => {
            this.achievementSound.load();
            this.completionSound.load();
        });
    }

    async loadChallengeData() {
        try {
            this.showLoadingState();

            const data = await apiClient.get(`/backend/challenge.php?id=${this.challengeId}&t=${Date.now()}`);
            if (!data) {
                this.showLoginRequired();
                return;
            }

            this.populateChallenge(data.challenge);
            this.setupEventListeners(data.challenge);
            this.showContent();

        } catch (error) {
            this.handleLoadError(error);
        }
    }

    showLoadingState() {
        this.loadingDiv.style.display = 'block';
        this.challengeContent.style.display = 'none';
        this.leaderboardSection.style.display = 'none';
        this.loginRequiredBanner.style.display = 'none';
    }

    showLoginRequired() {
        this.loadingDiv.style.display = 'none';
        this.loginRequiredBanner.style.display = 'block';
    }

    showContent() {
        this.loadingDiv.style.display = 'none';
        this.challengeContent.style.display = 'block';
        this.leaderboardSection.style.display = 'block';
    }

    populateChallenge(challenge) {
        this.populateBasicInfo(challenge);
        this.populateHints(challenge);
        this.updateChallengeStatus(challenge.challenge_status?.challenge_status || 'not_tried');
        this.handleDeploymentState(challenge);
        this.populateLeaderboard(challenge);
    }

    populateBasicInfo(challenge) {
        this.challengeTitle.textContent = challenge.name;
        this.challengeDescription.innerHTML = `
            ${this.escapeHtml(challenge.description)}<br><br>
            <em>~ by ${this.escapeHtml(challenge.creator_username || 'unknown')}</em>
        `;

        this.challengeCategory.textContent = challenge.category;
        this.challengeCategory.className = `challenge-category ${challenge.category.toLowerCase()}`;

        this.challengeDifficulty.textContent = challenge.difficulty;
        this.challengeDifficulty.className = `challenge-difficulty ${challenge.difficulty.toLowerCase()}`;

        this.challengePoints.textContent = `${challenge.challenge_points || 0} pts`;
        this.challengeSolves.textContent = `${challenge.solve_count || 0} solves`;

        if (!challenge.is_active) {
            this.showInactiveBanner();
            if (this.deployButton && !challenge.isCreator) {
                this.deployButton.disabled = true;
                this.deployButton.title = 'Challenge is inactive';
            }
        }

        if (challenge.marked_for_deletion) {
            this.showDeletionBanner();
        }

        this.challengeImage.src = challenge.image_path || '../assets/images/ctf-default.png';
        this.challengeImage.onerror = () => {
            this.challengeImage.src = '../assets/images/ctf-default.png';
        };
    }

    populateLeaderboard(challenge) {
        const leaderboard = challenge.leaderboard;
        if (!leaderboard || leaderboard.length === 0) {
            this.leaderboardContainer.innerHTML = `
                <tr>
                    <td colspan="3" class="leaderboard-empty">
                        No solves yet! Be the first to complete this challenge.
                    </td>
                </tr>
            `;
            return;
        }

        let html = '';

        leaderboard.forEach((entry, index) => {
            html += `
                <tr class="leaderboard-row" data-username="${this.escapeHtml(entry.username)}">
                    <td class="leaderboard-rank">${entry.rank}</td>
                    <td class="leaderboard-user">
                        <img src="${entry.avatar_url}" 
                             alt="${entry.username}" 
                             class="leaderboard-avatar"
                             onerror="this.src='/assets/avatars/default-avatar.png'">
                        ${this.escapeHtml(entry.username)}
                    </td>
                    <td class="leaderboard-time">${this.formatTime(entry.total_seconds)}</td>
                </tr>
            `;
        });

        this.leaderboardContainer.innerHTML = html;

        document.querySelectorAll('.leaderboard-row').forEach(row => {
            row.addEventListener('click', (e) => {
                const username = row.dataset.username;
                window.location.href = `/profile/${encodeURIComponent(username)}`;
            });

            row.addEventListener('mouseenter', () => {
                row.style.cursor = 'pointer';
            });
        });

        document.querySelector('.leaderboard-refresh')?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.loadChallengeData();
        });
    }

    formatTime(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;

        return [
            hours.toString().padStart(2, '0'),
            minutes.toString().padStart(2, '0'),
            secs.toString().padStart(2, '0')
        ].join(':');
    }

    escapeHtml(unsafe) {
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    updateChallengeStatus(status) {
        this.challengeStatus.textContent = status.replace('_', ' ');
        this.challengeStatus.className = `challenge-status ${status}`;
    }

    showInactiveBanner() {
        const existingBanner = this.challengeContent.querySelector('.challenge-banner.inactive');
        if (!existingBanner) {
            const banner = document.createElement('div');
            banner.className = 'challenge-banner inactive';
            banner.innerHTML = `
            <span class="banner-icon">⚠️</span>
            <span class="banner-text">This challenge is currently inactive and cannot be deployed</span>
        `;
            this.challengeContent.insertBefore(banner, this.challengeContent.firstChild);
        }
    }

    showDeletionBanner() {
        const existingBanner = this.challengeContent.querySelector('.challenge-banner.deletion');
        if(!existingBanner) {
            const banner = document.createElement('div');
            banner.className = 'challenge-banner deletion';
            banner.innerHTML = `
            <span class="banner-icon">🗑️</span>
            <span class="banner-text">This challenge is marked for deletion</span>
        `;
            this.challengeContent.insertBefore(banner, this.challengeContent.firstChild);
        }
    }

    handleDeploymentState(challenge) {
        const status = challenge.challenge_status?.challenge_status || 'not_tried';
        const isRunning = status === 'running';
        const isSolved = challenge.isSolved;

        this.deployButton.style.display = isRunning ? 'none' : 'inline-block';
        this.cancelButton.style.display = isRunning ? 'inline-block' : 'none';
        this.challengeTimerContainer.style.display = isRunning ? 'flex' : 'none';
        this.connectionInfo.style.display = isRunning ? 'block' : 'none';
        this.timerElement.style.display = isRunning ? 'block' : 'none';

        if (isRunning) {
            if (challenge.entrypoints?.length > 0) {
                this.displayConnectionInfo(challenge);
            }
            this.startTimer(challenge.elapsed_seconds || 0);
            if (challenge.remaining_seconds) {
                this.startChallengeTimer(challenge.remaining_seconds);
            }
        } else {
            this.stopTimer();
            this.stopChallengeTimer();
        }

        if (isSolved) {
            this.timerElement.classList.add('completed');
            this.stopTimer();
        } else {
            this.timerElement.classList.remove('completed');
        }
    }

    displayConnectionInfo(challenge) {
        this.subnetsContainer.innerHTML = '';

        const entrypointsList = document.createElement('div');
        entrypointsList.className = 'entrypoints-info';

        const title = document.createElement('h4');
        title.textContent = 'Entry Points: (Make sure that you are connected to the VPN, you can find your VPN config in your profile)';
        entrypointsList.appendChild(title);

        const list = document.createElement('ul');

        challenge.entrypoints.forEach(ip => {
            const item = document.createElement('li');
            const ipContainer = document.createElement('div');
            ipContainer.className = 'ip-container';

            const ipText = document.createElement('span');
            ipText.className = 'ip-address';
            ipText.textContent = ip;
            ipContainer.appendChild(ipText);

            const copyBtn = document.createElement('button');
            copyBtn.className = 'copy-btn';
            copyBtn.title = 'copy';
            copyBtn.onclick = () => this.copyToClipboard(ip, copyBtn);
            ipContainer.appendChild(copyBtn);

            item.appendChild(ipContainer);
            list.appendChild(item);
        });

        entrypointsList.appendChild(list);
        this.subnetsContainer.appendChild(entrypointsList);
    }

    copyToClipboard(text, button) {
        button.classList.add('copied');

        navigator.clipboard.writeText(text)
            .catch(err => {
                console.error('Failed to copy:', err);
                button.classList.add('copy-error');
                setTimeout(() => button.classList.remove('copy-error'), 2000);
            });

        setTimeout(() => {
            button.classList.remove('copied');
        }, 2000);
    }


    setupEventListeners(challenge) {
        this.cleanupEventListeners();

        if (this.deployButton) {
            this.deployButton.onclick = () => this.handleDeploy(challenge);
        }

        if (this.cancelButton) {
            this.cancelButton.onclick = () => this.handleCancel(challenge);
        }

        if (this.extendTimeButton) {
            this.extendTimeButton.onclick = () => this.handleExtendTime(challenge);
        }

        if (this.submitFlag) {
            this.submitFlag.onclick = () => this.handleFlagSubmission(challenge);
        }
    }

    cleanupEventListeners() {
        const cloneAndReplace = (element) => {
            if (element) {
                const newElement = element.cloneNode(true);
                element.parentNode.replaceChild(newElement, element);
                return newElement;
            }
            return null;
        };

        this.deployButton = cloneAndReplace(this.deployButton);
        this.cancelButton = cloneAndReplace(this.cancelButton);
        this.extendTimeButton = cloneAndReplace(this.extendTimeButton);
    }

    async handleDeploy(challenge) {
        try {
            this.setButtonState(this.deployButton, true, '<span class="button-icon">⏳</span> Deploying...');

            const data = await apiClient.post('/backend/challenge.php', {
                action: 'deploy',
                challenge_id: challenge.id
            });

            if (!data) return;

            this.updateChallengeStatus('running');
            this.deployButton.style.display = 'none';
            this.cancelButton.style.display = 'inline-block';
            this.challengeTimerContainer.style.display = 'flex';
            this.connectionInfo.style.display = 'block';
            this.timerElement.style.display = 'block';

            this.animateElement(this.challengeTimerContainer);
            this.displayConnectionInfo({...challenge, entrypoints: data.entrypoints || []});

            this.startTimer(data.elapsed_seconds || 0);

            if (challenge.isSolved) {
                this.timerElement.classList.add('completed');
                this.stopTimer();
            }

            this.startChallengeTimer(data.remaining_seconds);

        } catch (error) {
            messageManager.showError(error.message);
            this.setButtonState(this.deployButton, false, '<span class="button-icon">🚀</span> Deploy Challenge');
        }
    }

    async confirmAction(message) {
        return new Promise((resolve) => {
            const modal = document.createElement('div');
            modal.className = 'confirmation-modal';
            modal.innerHTML = `
                <div class="modal-content">
                    <p>${message}</p>
                    <div class="modal-buttons">
                        <button class="cancel-btn">No</button>
                        <button class="confirm-btn">Yes</button>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

            modal.querySelector('.cancel-btn').addEventListener('click', () => {
                document.body.removeChild(modal);
                resolve(false);
            });

            modal.querySelector('.confirm-btn').addEventListener('click', () => {
                document.body.removeChild(modal);
                resolve(true);
            });
        });
    }

    async handleCancel(challenge) {
        if (!await this.confirmAction('Are you sure you want to cancel this instance?')) return;

        try {
            this.setButtonState(this.cancelButton, true, '<span class="button-icon">⏳</span> Canceling...');

            const data = await apiClient.post('/backend/challenge.php', {
                action: 'cancel',
                challenge_id: challenge.id
            });

            if (!data) return;

            this.setButtonState(this.deployButton, false, '<span class="button-icon">🚀</span> Deploy Challenge');
            this.setButtonState(this.cancelButton, false, '<span class="button-icon">✖</span> Cancel Instance');

            this.deployButton.style.display = 'inline-block';
            this.challengeTimerContainer.style.display = 'none';
            this.cancelButton.style.display = 'none';
            this.connectionInfo.style.display = 'none';
            this.timerElement.style.display = 'none';

            this.stopChallengeTimer();
            this.stopTimer();

            this.setButtonState(this.cancelButton, false, '<span class="button-icon">✓</span> Canceled!');
            setTimeout(() => {
                this.loadChallengeData();
                this.setButtonState(this.cancelButton, false, '<span class="button-icon">✖</span> Cancel Instance');
            }, 1000);

        } catch (error) {
            messageManager.showError(error.message);
            this.setButtonState(this.cancelButton, false, '<span class="button-icon">✖</span> Cancel Instance');
        }
    }

    async handleExtendTime(challenge) {
        try {
            this.setButtonState(this.extendTimeButton, true, '<span class="button-icon">⏳</span> Extending...');

            const data = await apiClient.post('/backend/challenge.php', {
                action: 'extend_time',
                challenge_id: challenge.id
            });

            if (!data) return;

            if (data.remaining_seconds !== undefined) {
                this.startChallengeTimer(data.remaining_seconds);
            }

            messageManager.showSuccess(`Challenge time extended successfully! Remaining extensions: ${data.remaining_extensions}`);

        } catch (error) {
            messageManager.showError(error.message);
        } finally {
            this.setButtonState(this.extendTimeButton, false, '<span class="button-icon">⏱️</span> Extend Time');
        }
    }

    async handleFlagSubmission(challenge) {
        const flag = this.flagInput.value.trim();
        if (!flag) {
            this.showFlagFeedback('Please enter a flag', 'error');
            return;
        }

        try {
            this.setButtonState(this.submitFlag, true, '<span class="button-icon">⏳</span> Verifying...');

            const data = await apiClient.post('/backend/challenge.php', {
                action: 'submit_flag',
                challenge_id: challenge.id,
                flag: flag
            });

            if (!data) return;

            if (data.badges?.length > 0) {
                data.badges.forEach(badge => this.showAchievement(badge));
            }

            if (data.is_complete) {
                this.showCompletionAnimation(this.elapsedSeconds);
                this.updateChallengeStatus('solved');
                this.stopTimer();
            }

            this.showFlagFeedback(data.message || 'Flag accepted!', 'success');
            this.loadChallengeData();

        } catch (error) {
            this.showFlagFeedback(error.message, 'error');
        } finally {
            this.setButtonState(this.submitFlag, false, '<span class="button-icon">🏴</span> Submit');
            this.flagInput.value = '';
        }
    }

    setButtonState(button, disabled, html) {
        if (button) {
            button.disabled = disabled;
            button.innerHTML = html;
        }
    }

    showFlagFeedback(message, type) {
        if (this.flagFeedback) {
            this.flagFeedback.textContent = message;
            this.flagFeedback.className = `flag-feedback ${type}`;
        }
    }

    animateElement(element) {
        if (element) {
            element.style.opacity = '0';
            element.style.transition = 'opacity 0.3s ease';
            setTimeout(() => {
                element.style.opacity = '1';
            }, 50);
        }
    }


    startTimer(initialSeconds = 0) {
        this.elapsedSeconds = initialSeconds;
        this.updateTimerDisplay(this.elapsedSeconds);
        this.stopTimer();
        this.timerInterval = setInterval(() => {
            this.elapsedSeconds++;
            this.updateTimerDisplay(this.elapsedSeconds);
        }, 1000);
    }

    stopTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
    }

    updateTimerDisplay(totalSeconds) {
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;
        this.timerElement.textContent =
            `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }

    startChallengeTimer(seconds) {
        this.remainingSeconds = seconds;
        this.updateChallengeTimerDisplay();
        this.stopChallengeTimer();
        this.challengeTimerInterval = setInterval(() => {
            this.remainingSeconds--;
            this.updateChallengeTimerDisplay();
            if (this.remainingSeconds <= 0) {
                this.stopChallengeTimer();
            }
        }, 1000);
    }

    stopChallengeTimer() {
        if (this.challengeTimerInterval) {
            clearInterval(this.challengeTimerInterval);
            this.challengeTimerInterval = null;
        }
    }

    updateChallengeTimerDisplay() {
        const hours = Math.floor(this.remainingSeconds / 3600);
        const minutes = Math.floor((this.remainingSeconds % 3600) / 60);
        const seconds = this.remainingSeconds % 60;
        this.challengeTimerElement.textContent =
            `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }

    showAchievement(badge) {
        const notification = document.createElement('div');
        notification.className = 'achievement-notification';
        notification.innerHTML = `
            <div class="achievement-icon">🎖️</div>
            <div class="achievement-text">
                <h3>New Achievement Unlocked!</h3>
                <p>${badge}</p>
            </div>
        `;

        document.body.appendChild(notification);
        this.playSound(this.achievementSound);

        setTimeout(() => notification.classList.add('show'), 100);
        setTimeout(() => {
            notification.classList.remove('show');
            setTimeout(() => notification.remove(), 500);
        }, 5000);
    }

    showCompletionAnimation(elapsedSeconds) {
        const overlay = document.createElement('div');
        overlay.className = 'completion-overlay';

        const hours = Math.floor(elapsedSeconds / 3600);
        const minutes = Math.floor((elapsedSeconds % 3600) / 60);
        const seconds = elapsedSeconds % 60;
        const timeString = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;

        overlay.innerHTML = `
            <div class="completion-box">
                <div class="completion-title">Challenge Completed!</div>
                <div class="completion-time">Time: ${timeString}</div>
                <button class="button button-primary completion-continue-btn">
                    Continue
                </button>
            </div>
        `;

        document.body.appendChild(overlay);
        this.playSound(this.completionSound);

        overlay.querySelector('.completion-continue-btn').addEventListener('click', () => overlay.remove());
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) overlay.remove();
        });

        setTimeout(() => overlay.classList.add('show'), 100);
    }

    playSound(sound) {
        sound.play().catch(e => console.warn('Sound playback prevented:', e));
    }

    populateHints(challenge) {
        this.hintsContainer.innerHTML = '';

        if (challenge.hint?.trim()) {
            const hintSection = document.getElementById('hint-section');
            hintSection.style.display = 'block';
            this.hintsContainer.appendChild(this.createHintElement({
                hint_text: challenge.hint,
                unlock_points: 0
            }, true));
        }

        if (challenge.hints && challenge.hints.length > 0) {
            const hintSection = document.getElementById('hint-section');
            hintSection.style.display = 'block';
            challenge.hints.forEach((hint, index) => {
                this.hintsContainer.appendChild(this.createHintElement(hint, false, index));
            });
        }

        if (challenge.isSolved && challenge.solution !== "") {
            const solutionSection = document.getElementById('solution-section');
            solutionSection.style.display = 'block';
            document.getElementById('solution-text').textContent = challenge.solution;

            const solutionOverlay = document.querySelector('.solution-overlay');
            const solutionToggle = document.querySelector('.solution-toggle');

            const toggleSolutionVisibility = () => {
                const isHidden = solutionOverlay.classList.contains('hidden');
                solutionOverlay.classList.toggle('hidden', !isHidden);

                if (isHidden) {
                    solutionToggle.className = 'fa-solid fa-eye-slash solution-toggle';
                } else {
                    solutionToggle.className = 'fa-solid fa-eye solution-toggle';
                }
            };

            solutionOverlay.addEventListener('click', toggleSolutionVisibility);
            solutionToggle.addEventListener('click', toggleSolutionVisibility);
        }
    }

    createHintElement(hint, isGeneral, index = -1) {
        const hintElement = document.createElement('div');
        hintElement.className = 'hint-item';

        const hintHeader = document.createElement('div');
        hintHeader.className = 'hint-header';

        const hintTitle = document.createElement('span');
        hintTitle.className = 'hint-title';
        hintTitle.textContent = isGeneral ? 'General Hint' : 'Hint';

        if (index >= 0) {
            hintTitle.textContent += ` #${index + 1}`;
        }

        const hintPoints = document.createElement('span');
        hintPoints.className = 'hint-points';
        if (hint.unlock_points > 0) {
            hintPoints.textContent = `Unlocks at ${hint.unlock_points} pts`;
        }

        const hintContentWrapper = document.createElement('div');
        hintContentWrapper.className = 'hint-content-wrapper';

        const hintContent = document.createElement('div');
        hintContent.className = 'hint-content';
        hintContent.textContent = hint.hint_text;


        const overlay = document.createElement('div');
        overlay.className = 'hint-overlay';

        const hintToggle = document.createElement('i');
        hintToggle.className = 'fa-solid fa-eye hint-toggle';
        overlay.appendChild(hintToggle);


        overlay.addEventListener('click', () => {
            const isHidden = overlay.style.display !== 'none';
            overlay.style.display = isHidden ? 'none' : 'flex';
            hintToggle.className = isHidden ? 'fa-solid fa-eye-slash hint-toggle' : 'fa-solid fa-eye hint-toggle';
        });

        hintToggle.addEventListener('click', () => {
            const isHidden = overlay.style.display !== 'none';
            overlay.style.display = isHidden ? 'none' : 'flex';
            hintToggle.className = isHidden ? 'fa-solid fa-eye-slash hint-toggle' : 'fa-solid fa-eye hint-toggle';
        });

        hintContentWrapper.appendChild(hintContent);
        hintContentWrapper.appendChild(overlay);


        overlay.style.display = 'block';


        hintHeader.appendChild(hintTitle);
        if (hint.unlock_points > 0) hintHeader.appendChild(hintPoints);
        hintHeader.appendChild(hintToggle);


        hintElement.appendChild(hintHeader);
        hintElement.appendChild(hintContentWrapper);

        return hintElement;
    }


    handleLoadError(error) {
        this.loadingDiv.style.display = 'none';
        if (error.message.includes('Unauthorized') || error.message.includes('login')) {
            this.loginRequiredBanner.style.display = 'block';
        } else {
            messageManager.showError(error.message);
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new ChallengePage();
});