import {apiClient, messageManager} from './utils.js';
import themeToggle from './theme-toggle.js';

class ProfileManager {
    constructor() {
        this.selectedAvatar = null;
        this.categoryChart = null;

        this.unsubscribeTheme = themeToggle.subscribe(() => this.updateChartColors());

        this.loadConfig().then(() => {
            this.init();
        });
    }

    init() {
        const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
        this.initTabs();
        this.initRadarChart(currentTheme);
        this.initInlineEditors();
        this.initAvatarEditor();
        this.loadProfileData();
        this.initPasswordChangeModal();
        this.initVpnDownload();
        this.initAccountDeletion();
        this.initAiConsentToggle();
    }

    async loadConfig() {
        try {
            const response = await fetch('/config/general.config.json');
            const config = await response.json();
            this.config = config.user;

            this.config.USERNAME_REGEX = new RegExp(this.config.USERNAME_REGEX);
            this.config.EMAIL_REGEX = new RegExp(this.config.EMAIL_REGEX);
            this.config.FULL_NAME_REGEX = new RegExp(this.config.FULL_NAME_REGEX, 'u');
            this.config.GITHUB_REGEX = new RegExp(this.config.GITHUB_REGEX);
            this.config.TWITTER_REGEX = new RegExp(this.config.TWITTER_REGEX);
        } catch (error) {
            console.error('Failed to load config:', error);
        }
    }

    async loadProfileData() {
        try {
            const response = await apiClient.get('/backend/profile.php');
            if (!response) return;

            if (response.success) {
                this.updateProfileInfo(response.data.basic);
                this.updateStats(response.data.stats);
                this.updateBadges(response.data.badges);
                this.updateActivity(response.data.activity);
            }
        } catch (error) {
            console.error('Profile data load error:', error);
        }
    }

    updateProfileInfo(data) {
        document.getElementById('username-display').textContent = data.username;
        document.getElementById('full-name-value').textContent = data.full_name || 'N/A';
        document.getElementById('email-value').textContent = data.email;
        document.querySelector('.field-value[data-field="member_since"]').textContent =
            new Date(data.join_date).toLocaleDateString();
        document.querySelector('.bio-text').textContent = data.bio || 'No bio yet';
        document.querySelector('.points').textContent = `${data.points.toLocaleString()} points`;
        document.querySelector('.rank-badge').textContent = this.getRankTitle(data.points);

        if (data.avatar_url) {
            document.getElementById('user-avatar').src = data.avatar_url;
        }

        Object.entries(data.social_links || {}).forEach(([type, url]) => {
            const link = document.querySelector(`.social-link[data-type="${type}"]`);
            if (link) {
                link.href = url || '';
                link.classList.toggle('disabled', !url);
            }
        });

        const lastLoginDisplay = document.getElementById('last-login-display');
        if (lastLoginDisplay) {
            lastLoginDisplay.textContent = data.last_login || 'Never';
        }

        const aiConsentToggle = document.getElementById('ai-training-consent-toggle');
        if (aiConsentToggle) {
            aiConsentToggle.checked = data.ai_training_consent ?? true;
        }
    }

    initVpnDownload() {
        const downloadBtn = document.getElementById('download-vpn-config');
        if (!downloadBtn) return;

        const originalButtonHTML = downloadBtn.innerHTML;

        downloadBtn.addEventListener('click', async (e) => {
            e.preventDefault();

            try {
                downloadBtn.disabled = true;
                downloadBtn.innerHTML = `Generating Config...`;

                const result = await apiClient.post('/backend/profile.php', {
                    action: 'get_vpn_config'
                });

                if (!result) {
                    throw new Error('No response received');
                }

                if (result.success) {
                    messageManager.showSuccess(result?.message || 'VPN config downloaded successfully');
                } else {
                    throw new Error(result.message || 'Download failed');
                }
            } catch (error) {
                console.error('VPN download error:', error);
                messageManager.showError('Download failed');
            } finally {
                downloadBtn.disabled = false;
                downloadBtn.innerHTML = originalButtonHTML;
            }
        });
    }

    updateStats(data) {
        document.getElementById('total-solved').textContent = data.total_solved;
        document.getElementById('success-rate').textContent = `${data.success_rate}%`;
        document.getElementById('total-points').textContent = data.total_points.toLocaleString();

        if (this.categoryChart) {
            this.categoryChart.updateOptions({
                xaxis: {categories: data.categories}
            });

            this.categoryChart.updateSeries([{
                name: 'Completion',
                data: data.percentages
            }]);
        }

        if (data.categories && data.solved_counts) {
            data.categories.forEach(category => {
                const element = document.querySelector(`.category-stat[data-category="${category}"]`);
                if (element) {
                    element.textContent = `${data.solved_counts[category] || 0} solved`;
                }
            });
        }
    }

    updateBadges(data) {
        const badgesContainer = document.querySelector('.badges-grid');
        badgesContainer.innerHTML = '';

        data.badges.forEach(badge => {
            const badgeElement = document.createElement('div');
            badgeElement.className = 'badge-item';
            badgeElement.innerHTML = `
                <div class="badge-icon ${badge.color || 'gold'}">${badge.icon || '🏆'}</div>
                <div class="badge-title">${badge.name}</div>
            `;
            if (badge.description) {
                badgeElement.setAttribute('data-tooltip', badge.description);
            }
            badgesContainer.appendChild(badgeElement);
        });

        const lockedCount = data.total_badges - data.earned_count;
        for (let i = 0; i < lockedCount; i++) {
            const lockedElement = document.createElement('div');
            lockedElement.className = 'badge-item locked';
            lockedElement.innerHTML = `
                <div class="badge-icon">🔒</div>
                <div class="badge-title">Locked</div>
            `;
            lockedElement.setAttribute('data-tooltip', 'Badge Locked');
            badgesContainer.appendChild(lockedElement);
        }

        const badgeCount = document.getElementById('badge-count');
        badgeCount.textContent = `${data.earned_count}/${data.total_badges} unlocked`;
    }

    updateActivity(activities) {
        const activityContainer = document.querySelector('.activity-list');
        if (!activityContainer) return;

        activityContainer.innerHTML = activities.map(activity => {
            let icon, statusText;
            switch (activity.status) {
                case 'solved':
                    icon = '✅';
                    statusText = `Solved for ${activity.points} points`;
                    break;
                case 'failed':
                    icon = '⚠️';
                    statusText = `${activity.attempts} attempts`;
                    break;
                default:
                    icon = '🔍';
                    statusText = 'In progress';
            }

            return `
                <div class="activity-item" data-challenge-id="${activity.challenge_id}">
                    <div class="activity-icon">${icon}</div>
                    <div class="activity-content">
                        <div class="activity-title">${activity.challenge_name}</div>
                        <div class="activity-meta">
                            ${activity.category} • ${activity.time_ago} • ${statusText}
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    getRankTitle(points) {
        if (points >= 5000) return 'Elite Hacker';
        if (points >= 2000) return 'Advanced Hacker';
        if (points >= 1000) return 'Intermediate Hacker';
        if (points >= 500) return 'Novice Hacker';
        return 'Beginner';
    }

    initTabs() {
        const navItems = document.querySelectorAll(".nav-item");
        const sections = document.querySelectorAll(".info-section");

        navItems.forEach(item => {
            item.addEventListener("click", () => {
                navItems.forEach(btn => btn.classList.remove("active"));
                sections.forEach(section => section.classList.remove("active"));
                item.classList.add("active");
                const sectionId = item.dataset.section;
                document.getElementById(`${sectionId}-section`)?.classList.add("active");
            });
        });
    }

    initRadarChart(theme = 'dark') {
        const chartElement = document.getElementById("categoryChart");
        if (!chartElement) return;
        const primaryColor = getComputedStyle(document.documentElement).getPropertyValue('--color-primary');

        this.categoryChart = new ApexCharts(chartElement, {
            series: [{name: 'Completion', data: []}],
            chart: {
                type: 'radar',
                height: 300,
                toolbar: {show: false},
                background: 'transparent'
            },
            theme: {mode: theme},
            colors: [primaryColor],
            yaxis: {show: false, max: 100, min: 0},
            markers: {size: 5, hover: {size: 7}},
            tooltip: {
                y: {formatter: val => `${val}% completed`}
            },
            plotOptions: {
                radar: {
                    size: 120,
                    polygons: {
                        strokeColors: theme === 'light'
                            ? 'rgba(0, 0, 0, 0.2)'
                            : 'rgba(255, 255, 255, 0.1)',
                        fill: {
                            colors: [
                                theme === 'light'
                                    ? 'rgba(0, 0, 0, 0.05)'
                                    : 'rgba(255, 255, 255, 0.05)'
                            ]
                        }
                    }
                }
            },
            xaxis: {
                categories: [],
                labels: {
                    show: true,
                    style: {
                        colors: theme === 'light'
                            ? ['#212529','#212529','#212529','#212529','#212529','#212529']
                            : ['#fcfcfc','#fcfcfc','#fcfcfc','#fcfcfc','#fcfcfc','#fcfcfc'],
                        fontSize: "11px",
                        fontFamily: "Arial"
                    }
                }
            }
        });
        this.categoryChart.render();
    }

    initInlineEditors() {
        this.initUsernameEditor();
        this.initEmailEditor();
        this.initFullNameEditor()
        this.initBioEditor();
        this.initSocialLinksEditor();
    }

    updateChartColors() {
        const theme = document.documentElement.getAttribute('data-theme') || 'dark';
        const primaryColor = getComputedStyle(document.documentElement).getPropertyValue('--color-primary');

        if (this.categoryChart) {
            this.categoryChart.updateOptions({
                theme: {
                    mode: theme
                },
                colors: [primaryColor],
                plotOptions: {
                    radar: {
                        polygons: {
                            strokeColors: theme === 'light'
                                ? 'rgba(0, 0, 0, 0.2)'
                                : 'rgba(255, 255, 255, 0.1)',
                            fill: {
                                colors: [
                                    theme === 'light'
                                        ? 'rgba(0, 0, 0, 0.05)'
                                        : 'rgba(255, 255, 255, 0.05)'
                                ]
                            }
                        }
                    }
                },
                xaxis: {
                    labels: {
                        show: true,
                        style: {
                            colors: theme === 'light'
                                ? ['#212529','#212529','#212529','#212529','#212529','#212529']
                                : ['#fcfcfc','#fcfcfc','#fcfcfc','#fcfcfc','#fcfcfc','#fcfcfc'],
                            fontSize: "11px",
                            fontFamily: "Arial"
                        }
                    }
                },
            }, false, true);
        }
    }


    validateUsername(username) {
        const errors = [];
        const fields = [];

        if (!username) {
            errors.push('Username required');
            fields.push('username-input');
        } else if (username.length < this.config.MIN_USERNAME_LENGTH) {
            errors.push('Username too short');
            fields.push('username-input');
        } else if (username.length > this.config.MAX_USERNAME_LENGTH) {
            errors.push('Username too long');
            fields.push('username-input');
        } else if (!this.config.USERNAME_REGEX.test(username)) {
            errors.push('Invalid characters');
            fields.push('username-input');
        }

        return {errors, fields};
    }

    validateEmail(email) {
        const errors = [];
        const fields = [];

        if (!email) {
            errors.push('Email required');
            fields.push('email-input');
        } else if (email.length > this.config.MAX_EMAIL_LENGTH) {
            errors.push('Email too long');
            fields.push('email-input');
        } else if (!this.config.EMAIL_REGEX.test(email)) {
            errors.push('Invalid email');
            fields.push('email-input');
        }

        return {errors, fields};
    }

    validateFullName(fullName) {
        const errors = [];
        const fields = [];
        if (!fullName) {
            errors.push('Name required');
            fields.push('full-name-input');
        } else if (fullName.length < this.config.MIN_FULL_NAME_LENGTH) {
            errors.push('Name too short');
            fields.push('full-name-input');
        } else if (fullName.length > this.config.MAX_FULL_NAME_LENGTH) {
            errors.push('Name too long');
            fields.push('full-name-input');
        } else if (!this.config.FULL_NAME_REGEX.test(fullName)) {
            errors.push('Name contains invalid characters');
            fields.push('full-name-input');
        }

        return {errors, fields};
    }

    validateBio(bio) {
        const errors = [];
        const fields = [];

        if (bio.length > this.config.MAX_BIO_LENGTH) {
            errors.push('Bio too long');
            fields.push('bio-textarea');
        }

        return {errors, fields};
    }

    validateSocialLinks(links) {
        const errors = [];
        const fields = [];

        for (const [type, url] of Object.entries(links)) {
            const trimmedUrl = url.trim();
            if (trimmedUrl.length > this.config.MAX_SOCIAL_URL_LENGTH) {
                errors.push(`${type} URL too long`);
                fields.push(`${type}-input`);
                continue;
            }

            if (!trimmedUrl) continue;

            let isValid = false;

            if (type === 'github') {
                isValid = this.config.GITHUB_REGEX.test(trimmedUrl);
            } else if (type === 'twitter') {
                isValid = this.config.TWITTER_REGEX.test(trimmedUrl);
            } else if (type === 'website') {
                isValid = this.isValidUrl(trimmedUrl);
            } else {
                isValid = this.isValidUrl(trimmedUrl);
            }

            if (!isValid) {
                errors.push(`Invalid ${type} URL`);
                fields.push(`${type}-input`);
            }
        }

        return {errors, fields};
    }

    validatePasswordChange(currentPassword, newPassword, confirmPassword) {
        const errors = [];
        const fields = [];

        if (!currentPassword) {
            errors.push('Current password required');
            fields.push('currentPassword');
        }

        if (!newPassword) {
            errors.push('New password required');
            fields.push('newPassword');
        } else if (newPassword.length < this.config.MIN_PASSWORD_LENGTH) {
            errors.push('Password too short');
            fields.push('newPassword');
        } else if (newPassword.length > this.config.MAX_PASSWORD_LENGTH) {
            errors.push('Password too long');
            fields.push('newPassword');
        }

        if (!confirmPassword) {
            errors.push('Confirmation required');
            fields.push('confirmPassword');
        } else if (newPassword !== confirmPassword) {
            errors.push('Passwords mismatch');
            fields.push('confirmPassword');
        }

        return {errors, fields};
    }

    showValidationErrors(errors, fields) {
        let firstFieldElement = null;
        fields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                field.classList.add('error-field');

                if (!firstFieldElement) {
                    firstFieldElement = field;
                }

                field.addEventListener('input', () => {
                    field.classList.remove('error-field');
                }, {once: true});
            }
        });

        if (firstFieldElement) {
            firstFieldElement.focus();
            firstFieldElement.scrollIntoView({
                behavior: 'smooth',
                block: 'center'
            });
        }

        if (errors.length) {
            messageManager.showError(errors.join('<br>'));
            return false;
        }

        return true;
    }

    initUsernameEditor() {
        const editTrigger = document.querySelector('.edit-trigger[data-field="username"]');
        const display = document.getElementById('username-display');
        const editContainer = document.querySelector('.edit-container[data-field="username"]');

        if (!editTrigger || !display || !editContainer) return;

        const input = editContainer.querySelector('.edit-input');
        const saveBtn = editContainer.querySelector('.save-btn');
        const cancelBtn = editContainer.querySelector('.canc-btn');

        editTrigger.addEventListener('click', () => {
            input.value = display.textContent;
            editContainer.classList.remove('hidden');
            display.style.display = 'none';
            editTrigger.style.display = 'none';
            input.focus();
        });

        saveBtn.addEventListener('click', async () => {
            const newValue = input.value.trim();
            const {errors, fields} = this.validateUsername(newValue);
            if (!this.showValidationErrors(errors, fields)) return;

            try {
                const response = await apiClient.post('/backend/profile.php', {
                    action: 'update_username',
                    username: newValue
                });

                if (response?.success) {
                    input.classList.remove('error-field');
                    display.textContent = newValue;
                    editContainer.classList.add('hidden');
                    display.style.display = 'inline';
                    editTrigger.style.display = 'inline';
                    setTimeout(() => window.location.href = '/profile', 1500);
                    messageManager.showSuccess(response?.message || 'Username changed');
                } else {
                    this.showValidationErrors([], ['username-input']);
                }
            } catch (error) {
                console.error('Username update error:', error);
            }
        });

        cancelBtn.addEventListener('click', () => {
            editContainer.classList.add('hidden');
            display.style.display = 'inline';
            editTrigger.style.display = 'inline';
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') saveBtn.click();
            if (e.key === 'Escape') cancelBtn.click();
        });
    }

    initEmailEditor() {
        const editTrigger = document.querySelector('.edit-trigger[data-field="email"]');
        const valueElement = document.getElementById('email-value');
        const editContainer = document.querySelector('.edit-container[data-field="email"]');

        if (!editTrigger || !valueElement || !editContainer) return;

        const input = editContainer.querySelector('.edit-input');
        const saveBtn = editContainer.querySelector('.save-btn');
        const cancelBtn = editContainer.querySelector('.canc-btn');

        editTrigger.addEventListener('click', () => {
            input.value = valueElement.textContent;
            editContainer.classList.remove('hidden');
            valueElement.style.display = 'none';
            editTrigger.style.display = 'none';
            input.focus();
        });

        saveBtn.addEventListener('click', async () => {
            const newValue = input.value.trim();
            const {errors, fields} = this.validateEmail(newValue);
            if (!this.showValidationErrors(errors, fields)) return;

            try {
                const response = await apiClient.post('/backend/profile.php', {
                    action: 'update_email',
                    email: newValue
                });

                if (response?.success) {
                    valueElement.textContent = newValue;
                    editContainer.classList.add('hidden');
                    valueElement.style.display = 'inline';
                    editTrigger.style.display = 'inline';
                    messageManager.showSuccess(response?.message || 'Email changed');
                } else {
                    this.showValidationErrors([], ['email-input']);
                }
            } catch (error) {
                console.error('Email update error:', error);
            }
        });

        cancelBtn.addEventListener('click', () => {
            editContainer.classList.add('hidden');
            valueElement.style.display = 'inline';
            editTrigger.style.display = 'inline';
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') saveBtn.click();
            if (e.key === 'Escape') cancelBtn.click();
        });
    }

    initFullNameEditor() {
        const editTrigger = document.querySelector('.edit-trigger[data-field="full-name"]');
        const valueElement = document.getElementById('full-name-value');
        const editContainer = document.querySelector('.edit-container[data-field="full-name"]');

        if (!editTrigger || !valueElement || !editContainer) return;

        const input = editContainer.querySelector('.edit-input');
        const saveBtn = editContainer.querySelector('.save-btn');
        const cancelBtn = editContainer.querySelector('.canc-btn');

        editTrigger.addEventListener('click', () => {
            input.value = valueElement.textContent;
            editContainer.classList.remove('hidden');
            valueElement.style.display = 'none';
            editTrigger.style.display = 'none';
            input.focus();
        });

        saveBtn.addEventListener('click', async () => {
            const newValue = input.value.trim();
            const {errors, fields} = this.validateFullName(newValue);
            if (!this.showValidationErrors(errors, fields)) return;

            try {
                const response = await apiClient.post('/backend/profile.php', {
                    action: 'update_full_name',
                    full_name: newValue
                });

                if (response?.success) {
                    valueElement.textContent = newValue;
                    editContainer.classList.add('hidden');
                    valueElement.style.display = 'inline';
                    editTrigger.style.display = 'inline';
                    messageManager.showSuccess(response?.message || 'Name changed');
                } else {
                    this.showValidationErrors([], ['full-name-input']);
                }
            } catch (error) {
                console.error('Name update error:', error);
            }
        });

        cancelBtn.addEventListener('click', () => {
            editContainer.classList.add('hidden');
            valueElement.style.display = 'inline';
            editTrigger.style.display = 'inline';
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') saveBtn.click();
            if (e.key === 'Escape') cancelBtn.click();
        });
    }

    initBioEditor() {
        const bioText = document.querySelector('.bio-text');
        const editBtn = document.querySelector('.edit-bio-btn');
        const editContainer = document.querySelector('.edit-container[data-field="bio"]');
        const bioContainer = document.querySelector('.bio-container');

        if (!bioText || !editBtn || !editContainer) return;

        const textarea = editContainer.querySelector('.edit-textarea');
        const saveBtn = editContainer.querySelector('.save-btn');
        const cancelBtn = editContainer.querySelector('.canc-btn');

        editBtn.addEventListener('click', () => {
            textarea.value = bioText.textContent;
            editContainer.classList.remove('hidden');
            bioText.style.display = 'none';
            editBtn.style.display = 'none';
            textarea.focus();
        });

        saveBtn.addEventListener('click', async () => {
            const newValue = textarea.value.trim();
            const {errors, fields} = this.validateBio(newValue);
            if (!this.showValidationErrors(errors, fields)) return;

            try {
                const response = await apiClient.post('/backend/profile.php', {
                    action: 'update_bio',
                    bio: newValue
                });

                if (response?.success) {
                    bioText.textContent = newValue || 'No bio yet';
                    editContainer.classList.add('hidden');
                    bioText.style.display = 'block';
                    editBtn.style.display = 'block';
                    messageManager.showSuccess(response?.message || 'Bio changed');
                } else {
                    this.showValidationErrors([], ['bio-textarea']);
                }
            } catch (error) {
                console.error('Bio update error:', error);
            }
        });

        cancelBtn.addEventListener('click', () => {
            editContainer.classList.add('hidden');
            bioText.style.display = 'block';
            editBtn.style.display = 'block';
        });

        textarea.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === 'Enter') saveBtn.click();
        });
    }

    initSocialLinksEditor() {
        const editBtn = document.querySelector('.edit-social-btn');
        const editContainer = document.querySelector('.edit-container[data-field="social"]');

        if (!editBtn || !editContainer) return;

        const githubInput = editContainer.querySelector('input[data-type="github"]');
        const twitterInput = editContainer.querySelector('input[data-type="twitter"]');
        const websiteInput = editContainer.querySelector('input[data-type="website"]');
        const saveBtn = editContainer.querySelector('.save-btn');
        const cancelBtn = editContainer.querySelector('.canc-btn');

        editBtn.addEventListener('click', () => {
            const getCleanUrl = (type) => {
                const link = document.querySelector(`.social-link[data-type="${type}"]`);
                if (!link) return '';
                return (link.href === '' ||
                    link.href === window.location.href ||
                    link.href === '#')
                    ? ''
                    : link.href;
            };

            githubInput.value = getCleanUrl('github');
            twitterInput.value = getCleanUrl('twitter');
            websiteInput.value = getCleanUrl('website');

            editContainer.classList.remove('hidden');
            editBtn.style.display = 'none';
            githubInput.focus();
        });

        saveBtn.addEventListener('click', async () => {
            const newValues = {
                github: githubInput.value.trim(),
                twitter: twitterInput.value.trim(),
                website: websiteInput.value.trim()
            };

            const {errors, fields} = this.validateSocialLinks(newValues);
            if (!this.showValidationErrors(errors, fields)) return;

            try {
                const response = await apiClient.post('/backend/profile.php', {
                    action: 'update_social',
                    ...newValues
                });

                if (response?.success) {
                    Object.entries(newValues).forEach(([type, url]) => {
                        const link = document.querySelector(`.social-link[data-type="${type}"]`);
                        if (link) {
                            link.href = url || '';
                            link.classList.toggle('disabled', !url);
                        }
                    });

                    editContainer.classList.add('hidden');
                    editBtn.style.display = 'inline-block';
                    messageManager.showSuccess(response?.message || 'Social Links updated');
                } else {
                    this.showValidationErrors([], ['github-input', 'twitter-input', 'website-input']);
                }
            } catch (error) {
                console.error('Social links update error:', error);
            }
        });

        cancelBtn.addEventListener('click', () => {
            editContainer.classList.add('hidden');
            editBtn.style.display = 'inline-block';
        });
    }

    initAvatarEditor() {
        const editAvatarBtn = document.querySelector('.edit-avatar');
        if (!editAvatarBtn) return;

        const avatarModal = document.createElement('div');
        avatarModal.className = 'avatar-modal';
        avatarModal.innerHTML = `
        <div class="avatar-modal-content">
            <h3>Change Avatar</h3>
            <div class="avatar-options">
                <div class="avatar-option" data-avatar="shuffle" title="Random avatar">
                    <img src="/assets/avatars/shuffle-icon.png" alt="Shuffle">
                </div>
                <div class="avatar-option" data-avatar="avatar1">
                    <img src="/assets/avatars/avatar1.png" alt="Avatar 1">
                </div>
                <div class="avatar-option" data-avatar="avatar2">
                    <img src="/assets/avatars/avatar2.png" alt="Avatar 2">
                </div>
                <div class="avatar-option" data-avatar="avatar3">
                    <img src="/assets/avatars/avatar3.png" alt="Avatar 3">
                </div>
            </div>
            <div class="upload-preview-container"></div>
            <div class="avatar-upload">
                <label for="avatar-upload" class="upload-label">Upload custom:</label>
                <div class="button-row">
                    <div class="upload-button-container">
                        <input type="file" id="avatar-upload" accept="image/*" style="display: none;">
                        <label for="avatar-upload" class="button button-primary">Choose File</label>
                    </div>
                    <div class="avatar-modal-buttons">
                        <button class="button button-secondary cancel-avatar-btn">Cancel</button>
                        <button class="button button-primary save-avatar-btn" disabled>Save</button>
                    </div>
                </div>
            </div>
        </div>
    `;

        document.body.appendChild(avatarModal);

        editAvatarBtn.addEventListener('click', () => this.showAvatarModal(avatarModal));

        avatarModal.addEventListener('click', (e) => {
            if (e.target === avatarModal || e.target.classList.contains('cancel-avatar-btn')) {
                this.hideAvatarModal(avatarModal);
            }
        });

        const saveAvatarBtn = avatarModal.querySelector('.save-avatar-btn');
        saveAvatarBtn.addEventListener('click', async () => {
            await this.saveAvatar(avatarModal);
        });

        avatarModal.querySelectorAll('.avatar-option').forEach(option => {
            option.addEventListener('click', () => {
                option.parentNode.querySelectorAll('.avatar-option').forEach(opt => {
                    opt.classList.remove('selected');
                });
                option.classList.add('selected');
                avatarModal.querySelector('.save-avatar-btn').disabled = false;

                if (option.dataset.avatar === 'shuffle') {
                    const randomAvatar = ['avatar1', 'avatar2', 'avatar3'][Math.floor(Math.random() * 3)];
                    option.classList.remove('selected');
                    const randomAvatarOption = option.parentNode.querySelector(`.avatar-option[data-avatar="${randomAvatar}"]`);
                    if (randomAvatarOption) {
                        randomAvatarOption.classList.add('selected');
                    }
                    this.selectedAvatar = randomAvatar;
                } else {
                    this.selectedAvatar = option.dataset.avatar;
                }
            });
        });

        const avatarUpload = avatarModal.querySelector('#avatar-upload');
        avatarUpload.addEventListener('change', (e) => {
            if (e.target.files?.[0]) {
                const file = e.target.files[0];
                if (!this.config.ALLOWED_AVATAR_TYPES.includes(file.type)) {
                    messageManager.showError('Invalid image type');
                    return;
                }
                if (file.size > this.config.MAX_AVATAR_SIZE) {
                    messageManager.showError('Image too large (max 2MB)');
                    return;
                }

                const reader = new FileReader();
                reader.onload = (e) => {
                    this.selectedAvatar = e.target.result;
                    avatarModal.querySelector('.save-avatar-btn').disabled = false;

                    const previewContainer = avatarModal.querySelector('.upload-preview-container');
                    previewContainer.innerHTML = '';

                    const uploadedOption = document.createElement('div');
                    uploadedOption.className = 'avatar-option upload-preview selected';
                    uploadedOption.dataset.avatar = 'uploaded';

                    const img = document.createElement('img');
                    img.src = e.target.result;
                    img.alt = 'Uploaded';

                    uploadedOption.appendChild(img);
                    previewContainer.appendChild(uploadedOption);

                    uploadedOption.addEventListener('click', () => {
                        avatarModal.querySelectorAll('.avatar-option').forEach(opt => {
                            opt.classList.remove('selected');
                        });
                        uploadedOption.classList.add('selected');
                        this.selectedAvatar = e.target.result;
                    });
                };
                reader.readAsDataURL(file);
            }
        });
    }

    showAvatarModal(modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }

    hideAvatarModal(modal) {
        modal.style.display = 'none';
        document.body.style.overflow = '';
        modal.querySelector('#avatar-upload').value = '';
        modal.querySelector('.save-avatar-btn').disabled = true;
        this.selectedAvatar = null;
    }

    async saveAvatar(modal) {
        if (!this.selectedAvatar) return;

        try {
            let response;

            if (typeof this.selectedAvatar === 'string' && this.selectedAvatar.startsWith('data:')) {
                const formData = new FormData();
                const blob = await fetch(this.selectedAvatar).then(r => r.blob());
                formData.append('avatar', blob, 'avatar.png');
                formData.append('action', 'upload_avatar');

                response = await apiClient.post('/backend/profile.php', formData);
            } else {
                response = await apiClient.post('/backend/profile.php', {
                    action: 'update_avatar',
                    avatar: this.selectedAvatar
                });
            }

            if (response?.success) {
                const avatarUrl = response.avatar_url
                    ? `${response.avatar_url}?t=${Date.now()}`
                    : `/assets/avatars/${this.selectedAvatar}.png`;

                document.getElementById('user-avatar').src = avatarUrl;
                document.getElementById('avatar-img').src = avatarUrl;

                messageManager.showSuccess(response?.message || 'Avatar updated');
                setTimeout(() => this.hideAvatarModal(modal), 1500);
            }
        } catch (error) {
            console.error('Avatar save error:', error);
            messageManager.showError('Update failed');
        }
    }

    initPasswordChangeModal() {
        const changePasswordBtn = document.querySelector('.action-link[data-action="change-password"]');
        const modal = document.getElementById('passwordModal');
        const cancelBtn = modal?.querySelector('.cancel-button');
        const saveBtn = modal?.querySelector('.save-button');

        if (!changePasswordBtn || !modal) return;

        changePasswordBtn.addEventListener('click', (e) => {
            e.preventDefault();
            modal.style.display = 'flex';
            document.getElementById('currentPassword').focus();
        });

        cancelBtn?.addEventListener('click', () => {
            modal.style.display = 'none';
            modal.querySelectorAll('input').forEach(input => input.value = '');
        });

        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
                modal.querySelectorAll('input').forEach(input => input.value = '');
            }
        });

        saveBtn?.addEventListener('click', async () => {
            const currentPasswordField = document.getElementById('currentPassword');
            const newPasswordField = document.getElementById('newPassword');
            const confirmPasswordField = document.getElementById('confirmPassword');

            const currentPassword = currentPasswordField.value;
            const newPassword = newPasswordField.value;
            const confirmPassword = confirmPasswordField.value;

            const {errors, fields} = this.validatePasswordChange(currentPassword, newPassword, confirmPassword);
            if (!this.showValidationErrors(errors, fields)) return;

            try {
                saveBtn.disabled = true;

                const response = await apiClient.post('/backend/profile.php', {
                    action: 'change_password',
                    current_password: currentPassword,
                    new_password: newPassword
                });

                if (response?.success) {
                    messageManager.showSuccess(response?.message || 'Password changed');
                    modal.querySelectorAll('input').forEach(input => input.value = '');
                    setTimeout(() => {
                        modal.style.display = 'none';
                    }, 1500);
                } else {
                    [currentPasswordField, newPasswordField, confirmPasswordField].forEach(field => {
                        field.value = '';
                    })
                    this.showValidationErrors([], ['currentPassword', 'newPassword', 'confirmPassword']);
                }
            } catch (error) {
                console.error('Failed to change Password:', error);
            } finally {
                saveBtn.disabled = false;
            }
        });

        modal?.querySelectorAll('input').forEach(input => {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') saveBtn.click();
            });
        });
    }

    initAccountDeletion() {
        const deleteBtn = document.getElementById('delete-account-btn');
        const modal = document.getElementById('deleteAccountModal');

        if (!deleteBtn || !modal) return;

        deleteBtn.addEventListener('click', (e) => {
            e.preventDefault();
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
            modal.querySelector('#confirmPasswordForDeletion').focus();
        });

        modal.querySelector('.canc-btn').addEventListener('click', () => {
            modal.style.display = 'none';
            document.body.style.overflow = '';
            modal.querySelector('#confirmPasswordForDeletion').value = '';
        });

        modal.querySelector('#confirm-delete-btn').addEventListener('click', async () => {
            const password = modal.querySelector('#confirmPasswordForDeletion').value.trim();
            const confirmBtn = modal.querySelector('#confirm-delete-btn');

            if (!password) {
                return;
            }

            try {
                confirmBtn.disabled = true;
                confirmBtn.textContent = 'Deleting...';

                const response = await apiClient.delete('/backend/profile.php', {
                    data: {password}
                });

                if (!response?.success) {
                    throw new Error(response?.message || 'Deletion failed');
                }

                messageManager.showSuccess(response?.message || 'Account deleted');
                setTimeout(() => window.location.href = '/', 2000);

            } catch (error) {
                confirmBtn.disabled = false;
                confirmBtn.textContent = 'Delete Account';
            }
        });

        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
                document.body.style.overflow = '';
                modal.querySelector('#confirmPasswordForDeletion').value = '';
            }
        });

        modal.querySelector('#confirmPasswordForDeletion').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                modal.querySelector('#confirm-delete-btn').click();
            }
        });
    }

    initAiConsentToggle() {
        const toggle = document.getElementById('ai-training-consent-toggle');
        if (!toggle) return;

        toggle.addEventListener('change', async (e) => {
            const consent = e.target.checked;
            const previousState = !consent;

            try {
                const response = await apiClient.post('/backend/profile.php', {
                    action: 'update_ai_consent',
                    consent: consent
                });

                if (response?.success) {
                    messageManager.showSuccess(response?.message || 'Privacy preferences updated');
                } else {
                    toggle.checked = previousState;
                    messageManager.showError(response?.message || 'Failed to update preferences');
                }
            } catch (error) {
                toggle.checked = previousState;
                console.error('AI consent update error:', error);
                messageManager.showError('Failed to update privacy preferences');
            }
        });
    }


    isValidUrl(string) {
        try {
            new URL(string);
            return true;
        } catch (_) {
            return false;
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new ProfileManager();
});