<?php
declare(strict_types=1);
require_once __DIR__ . '/../vendor/autoload.php';

$securityHelper = new SecurityHelper();
$securityHelper->initSecureSession();

if (!$securityHelper->validateSession()) {
    header('Location: /404');
    exit();
}
?>

<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your Profile | heiST</title>
    <link rel="icon" type="image/svg+xml" href="/assets/icons/favicon.svg">
    <link rel="stylesheet" href="../assets/css/base.css">
    <link rel="stylesheet" href="../assets/css/profile.css">
    <script src="https://cdn.jsdelivr.net/npm/apexcharts@3.44.0/dist/apexcharts.min.js" defer></script>
</head>
<body>
<?php include($_SERVER['DOCUMENT_ROOT'] . '/partials/header.html'); ?>
<main class="profile-container">
    <div class="profile-grid">
        <section class="account-info-card">
            <div class="account-info-nav">
                <div class="nav-header">
                    <h2>Account Information</h2>
                </div>
                <nav class="info-sections-nav">
                    <button class="nav-item active" data-section="public">Public Information</button>
                    <button class="nav-item" data-section="basic">Basic Information</button>
                    <button class="nav-item" data-section="security">Security</button>
                    <button class="nav-item" data-section="vpn">Vpn</button>
                </nav>
            </div>

            <div class="account-info-content">
                <div class="info-section active" id="public-section">
                    <div class="avatar-section">
                        <div class="avatar-edit">
                            <img id="user-avatar" src="../assets/avatars/default-avatar.png" alt="User Avatar">
                            <button class="edit-avatar" title="Change Avatar">✎</button>
                        </div>
                        <div class="avatar-info">
                            <div class="user-member-group">
                                <div class="user-field">
                                    <div class="username-display-container">
                                        <div class="field-with-action">
                                            <h1 id="username-display" class="field-value">Loading...</h1>
                                            <button class="action-link edit-trigger" data-field="username">Edit</button>
                                            <div class="edit-container hidden" data-field="username">
                                                <input id="username-input" type="text" class="edit-input" value="">
                                                <div class="edit-buttons">
                                                    <button class="save-btn">Save</button>
                                                    <button class="canc-btn">Cancel</button>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="edit-container hidden" data-field="username">
                                        <div class="edit-input-group">
                                            <input type="text" class="edit-input" value="">
                                            <div class="edit-buttons">
                                                <button class="save-btn">Save</button>
                                                <button class="canc-btn">Cancel</button>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div class="info-field member-since">
                                    <span class="field-label">Member Since</span>
                                    <span class="field-value" data-field="member_since">Loading...</span>
                                </div>
                            </div>
                            <div class="user-rank">
                                <span class="rank-badge">Loading rank</span>
                                <span class="points">0 points</span>
                            </div>
                        </div>
                    </div>
                    <div class="info-content-wrapper">
                        <div class="info-field bio-field">
                            <span class="field-label">Bio</span>
                            <div class="bio-container">
                                <p class="bio-text">Loading bio...</p>
                                <button class="edit-bio-btn">
                                    <svg class="edit-icon" viewBox="0 0 24 24">
                                        <path fill="currentColor"
                                              d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
                                    </svg>
                                </button>
                                <div class="edit-container hidden" data-field="bio">
                                    <textarea id="bio-textarea" class="edit-textarea"
                                              placeholder="Tell us about yourself..."></textarea>
                                    <div class="edit-controls">
                                        <button class="icon-btn save-btn" title="Save">
                                            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"
                                                 viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                                                 stroke-linecap="round" stroke-linejoin="round">
                                                <polyline points="20 6 9 17 4 12"></polyline>
                                            </svg>
                                        </button>
                                        <button class="icon-btn canc-btn" title="Cancel">
                                            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"
                                                 viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                                                 stroke-linecap="round" stroke-linejoin="round">
                                                <line x1="18" y1="6" x2="6" y2="18"></line>
                                                <line x1="6" y1="6" x2="18" y2="18"></line>
                                            </svg>
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="social-links-container">
                        <div class="info-field">
                            <div class="social-links-header">
                                <span class="field-label">Social Links</span>
                                <button class="edit-social-btn">
                                    <svg class="edit-icon" viewBox="0 0 24 24">
                                        <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
                                    </svg>
                                    Edit
                                </button>
                            </div>
                            <div class="social-links">
                                <a href="#" class="social-link" data-type="github">
                                    <svg class="social-icon" viewBox="0 0 24 24">
                                        <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                                    </svg>
                                    GitHub
                                </a>
                                <a href="#" class="social-link" data-type="twitter">
                                    <svg class="social-icon" viewBox="0 0 24 24">
                                        <path d="M23.953 4.57a10 10 0 01-2.825.775 4.958 4.958 0 002.163-2.723c-.951.555-2.005.959-3.127 1.184a4.92 4.92 0 00-8.384 4.482C7.69 8.095 4.067 6.13 1.64 3.162a4.822 4.822 0 00-.666 2.475c0 1.71.87 3.213 2.188 4.096a4.904 4.904 0 01-2.228-.616v.06a4.923 4.923 0 003.946 4.827 4.996 4.996 0 01-2.212.085 4.936 4.936 0 004.604 3.417 9.867 9.867 0 01-6.102 2.105c-.39 0-.779-.023-1.17-.067a13.995 13.995 0 007.557 2.209c9.053 0 13.998-7.496 13.998-13.985 0-.21 0-.42-.015-.63A9.935 9.935 0 0024 4.59z"/>
                                    </svg>
                                    Twitter
                                </a>
                                <a href="#" class="social-link" data-type="website">
                                    <svg class="social-icon" viewBox="0 0 24 24">
                                        <path d="M12 0C8.688 0 6 2.688 6 6s2.688 6 6 6 6-2.688 6-6-2.688-6-6-6zm0 10c-2.206 0-4-1.794-4-4s1.794-4 4-4 4 1.794 4 4-1.794 4-4 4zm7.5-1.5c-.828 0-1.5.672-1.5 1.5s.672 1.5 1.5 1.5 1.5-.672 1.5-1.5-.672-1.5-1.5-1.5zM23.994 22v-.002c0-.438-.095-.864-.275-1.262-.545-1.229-1.756-2.062-3.219-2.062h-16c-1.463 0-2.674.833-3.219 2.062-.18.398-.275.824-.275 1.262v.002h23.988zM22 12v10h-5v-6c0-1.104-.896-2-2-2s-2 .896-2 2v6h-5V12h-2v10h-1.994c.004-.063.012-.125.012-.188 0-1.656 1.344-3 3-3h16c1.656 0 3 1.344 3 3 0 .063.008.125.012.188h-2.012V12h-2z"/>
                                    </svg>
                                    Website
                                </a>
                            </div>
                            <div class="edit-container hidden" data-field="social">
                                <div class="edit-input-group">
                                    <label>GitHub URL</label>
                                    <input id="github-input" type="url" class="edit-input" data-type="github"
                                           placeholder="https://github.com/username">
                                </div>
                                <div class="edit-input-group">
                                    <label>Twitter URL</label>
                                    <input id="twitter-input" type="url" class="edit-input" data-type="twitter"
                                           placeholder="https://twitter.com/username">
                                </div>
                                <div class="edit-input-group">
                                    <label>Website URL</label>
                                    <input id="website-input" type="url" class="edit-input" data-type="website"
                                           placeholder="https://yourwebsite.com">
                                </div>
                                <div class="edit-buttons">
                                    <button class="save-btn">Save</button>
                                    <button class="canc-btn">Cancel</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="info-section" id="basic-section">
                    <div class="info-content-wrapper">
                        <div class="info-list">
                            <div class="info-field">
                                <span class="field-label">Full Name</span>
                                <div class="field-with-action">
                                    <span class="field-value" id="full-name-value">Loading...</span>
                                    <button class="action-link edit-trigger" data-field="full-name">Change</button>
                                    <div class="edit-container hidden" data-field="full-name">
                                        <input id="full-name-input" type="text" class="edit-input" value="">
                                        <button class="save-btn">Save</button>
                                        <button class="canc-btn">Cancel</button>
                                    </div>
                                </div>

                            </div>
                            <div class="info-field email-verified-group">
                                <div class="email-field">
                                    <span class="field-label">Email Address</span>
                                    <div class="field-with-action">
                                        <span class="field-value" id="email-value">Loading...</span>
                                        <button class="action-link edit-trigger" data-field="email">Change</button>
                                        <div class="edit-container hidden" data-field="email">
                                            <input id="email-input" type="email" class="edit-input" value="">
                                            <button class="save-btn">Save</button>
                                            <button class="canc-btn">Cancel</button>
                                        </div>
                                    </div>
                                </div>
                                <div class="info-field">
                                    <span class="field-label">Verified</span>
                                    <span class="field-value verified error">No</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="info-section" id="security-section">
                    <div class="info-content-wrapper">
                        <div class="info-list">
                            <div class="info-field">
                                <span class="field-label">Password</span>
                                <div class="field-with-action">
                                    <span class="field-value">••••••••</span>
                                    <button class="action-link" data-action="change-password" id="change-password-btn">
                                        Change
                                    </button>
                                </div>
                            </div>
                            <div class="info-field">
                                <span class="field-label">2FA</span>
                                <div class="field-with-action">
                                    <span class="field-value">Disabled</span>
                                    <button class="action-link" id="manage-2fa-btn">Enable</button>
                                </div>
                            </div>
                            <div class="info-field">
                                <span class="field-label">Last Login</span>
                                <span class="field-value" id="last-login-display">Never</span>
                            </div>
                        <div class="info-field privacy-section">
                                <div class="privacy-header">
                                    <span class="field-label">Privacy & Data Usage</span>
                                </div>
                                <div class="privacy-option">
                                    <div class="privacy-info">
                                        <div class="privacy-title">AI Training Data</div>
                                        <div class="privacy-description">
                                            Allow your anonymized data to be used for improving our AI models
                                        </div>
                                    </div>
                                    <label class="option-switch">
                                        <input type="checkbox" id="ai-training-consent-toggle">
                                        <span class="option-slider round"></span>
                                    </label>
                                </div>
                            </div>
                            <div class="info-field danger-zone">
                                <span class="field-label">Account Deletion</span>
                                <div class="field-with-action">
                                    <span class="field-value">Permanently delete your account</span>
                                    <button class="action-link danger" id="delete-account-btn">Delete Account</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="info-section" id="vpn-section">
                    <div class="info-content-wrapper">
                        <div class="vpn-container">
                            <h3>VPN Configuration</h3>
                            <div class="vpn-download">
                                <h4>OpenVPN Configuration</h4>
                                <p>Download your personalized VPN configuration file to connect to our network:</p>
                                <button id="download-vpn-config" class="vpn-download-btn">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"
                                         fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
                                         stroke-linejoin="round">
                                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                                        <polyline points="7 10 12 15 17 10"></polyline>
                                        <line x1="12" y1="15" x2="12" y2="3"></line>
                                    </svg>
                                    Download VPN Config
                                </button>
                                <p class="vpn-instructions">
                                    <strong>Instructions:</strong> Import this file into your OpenVPN client to connect.
                                </p>
                            </div>

                            <div class="vpn-help">
                                <h4>Need Help?</h4>
                                <ul>
                                    <li><a href="https://openvpn.net/frequently-asked-questions/" target="_blank">VPN
                                            Setup Guide</a></li>
                                </ul>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>
        <section class="profile-card stats-overview">
            <h2>Your Stats</h2>
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-value" id="total-solved">0</div>
                    <div class="stat-label">Challenges Solved</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value" id="success-rate">0%</div>
                    <div class="stat-label">Success Rate</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value" id="total-points">0</div>
                    <div class="stat-label">Total Points</div>
                </div>
            </div>
            <div class="stat-chart">
                <div id="categoryChart"></div>
            </div>
        </section>
        <section class="profile-card achievements">
            <div class="card-header">
                <h2>Badges & Achievements</h2>
                <span class="badge-count" id="badge-count">0/0 unlocked</span>
            </div>
            <div class="badges-grid" id="badges-grid">
                <!-- This will be populated by JavaScript -->
                <div class="badge-item loading">
                    <div class="badge-icon">⌛</div>
                    <div class="badge-title">Loading...</div>
                </div>
            </div>
            <div class="view-all-container">
                <a href="/badges" class="view-all">View all achievements →</a>
            </div>
        </section>
    </div>
</main>
<?php include($_SERVER['DOCUMENT_ROOT'] . '/partials/footer.html'); ?>
<div class="modal" id="passwordModal">
    <div class="modal-content">
        <h3>Change Password</h3>
        <div class="form-group">
            <label for="currentPassword">Current Password</label>
            <input type="password" id="currentPassword" required>
        </div>
        <div class="form-group">
            <label for="newPassword">New Password</label>
            <input type="password" id="newPassword" required>
        </div>
        <div class="form-group">
            <label for="confirmPassword">Confirm New Password</label>
            <input type="password" id="confirmPassword" required>
        </div>
        <div class="modal-buttons">
            <button class="button button-secondary cancel-button">Cancel</button>
            <button class="button button-primary save-button">Save Changes</button>
        </div>
    </div>
</div>
<div class="modal" id="deleteAccountModal">
    <div class="modal-content">
        <h3>Delete Your Account</h3>
        <div class="warning-message">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                <line x1="12" y1="9" x2="12" y2="13"></line>
                <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
            <p>This action cannot be undone. All your data, including solved challenges and achievements, will be
                permanently deleted.</p>
        </div>
        <div class="form-group">
            <label for="confirmPasswordForDeletion">Enter your password to confirm</label>
            <input type="password" id="confirmPasswordForDeletion" required>
        </div>
        <div class="modal-buttons">
            <button class="button button-secondary btn canc-btn">Cancel</button>
            <button class="button btn-confirm btn btn-danger" id="confirm-delete-btn">Delete Account Permanently
            </button>
        </div>
    </div>
</div>

<script type="module" src="../assets/js/theme-toggle.js"></script>
<script type="module" src="../assets/js/profile.js"></script>
</body>
</html>
