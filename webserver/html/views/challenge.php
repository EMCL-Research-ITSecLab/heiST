<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Challenge - heiST</title>
    <link rel="icon" type="image/svg+xml" href="/assets/icons/favicon.svg">
    <link rel="stylesheet" href="../assets/css/base.css">
    <link rel="stylesheet" href="../assets/css/challenge.css">
</head>
<body>
<?php include($_SERVER['DOCUMENT_ROOT'] . '/partials/header.html'); ?>
<div class="main-wrapper">
    <main class="challenge-container">
        <div class="back-button-container">
            <a href="/explore" class="back-button">
                <span class="arrow">←</span> Back to Challenges
            </a>
        </div>

        <div class="login-required-banner" style="display: none;">
            <div class="login-banner-content">
                <div class="login-banner-icon">🔒</div>
                <div class="login-banner-text">
                    <h3>Authentication Required</h3>
                    <p>You need to be logged in to view this challenge.</p>
                </div>
                <div class="login-banner-actions">
                    <a href="/login" class="button button-primary">Login</a>
                    <a href="/register" class="button button-secondary">Register</a>
                </div>
            </div>
        </div>

        <div class="loading">Loading challenge...</div>

        <div class="challenge-content" style="display: none;">
            <div class="challenge-header">
                <div class="challenge-image-container">
                    <img id="challenge-image" src="" alt="Challenge Image" class="challenge-image">
                    <div class="challenge-image-overlay"></div>
                </div>
                <div class="challenge-meta">
                    <div class="challenge-status-container">
                        <span id="challenge-status" class="challenge-status"></span>
                    </div>
                    <h1 id="challenge-title"></h1>
                    <div class="challenge-stats">
                        <span id="challenge-category" class="challenge-category"></span>
                        <span id="challenge-difficulty" class="challenge-difficulty"></span>
                        <span id="challenge-points" class="challenge-points"></span>
                        <span id="challenge-solves" class="challenge-solves"></span>
                    </div>
                    <div class="description" id="challenge-description"></div>
                </div>
            </div>

            <div class="challenge-body">


                <div class="challenge-instance-section">
                    <h2>Challenge Instance</h2>
                    <div class="instance-actions">
                        <button id="deploy-button" class="button button-primary">
                            <span class="button-icon">🚀</span> Deploy Challenge
                        </button>
                        <div class="running-action-container">
                            <div class="cancel-timer-container">
                                <button id="cancel-button" class="button button-danger" style="display: none;">
                                    <span class="button-icon">✖</span> Cancel Instance
                                </button>
                                <div class="challenge-timer" id="timer"></div>
                            </div>
                            <div class="challenge-timer-container" style="display: none;">
                                <div class="challenge-timer" id="challenge-timer">00:00:00</div>
                                <button id="extend-time-button" class="button button-warning">
                                    <span class="button-icon">⏱️</span> Extend Time
                                </button>
                            </div>
                        </div>
                    </div>
                    <div class="connection-info" id="connection-info" style="display: none;">
                        <h3>Connection Information</h3>
                        <div class="subnets-container" id="subnets-container"></div>
                    </div>
                </div>

                <div class="hint-section" id="hint-section" style="display: none;">
                    <h2>Hints</h2>
                    <div class="hints-container" id="hints-container"></div>
                </div>

                <div class="solution-section" id="solution-section" style="display: none;">
                    <h2>Solution</h2>
                    <div class="solution-container">
                        <div class="solution-content-wrapper">
                            <div class="solution-toggle-container">
                                <i class="fa-solid fa-eye solution-toggle"></i>
                            </div>
                            <textarea id="solution-text" class="solution-text" readonly></textarea>
                            <div class="solution-overlay"></div>
                        </div>
                    </div>
                </div>

                <div class="flag-section">
                    <div class="flag-section-header">
                        <h2>Submit Flag</h2>
                        <div class="flag-progress empty" id="flag-progress">
                            <svg viewBox="0 0 80 80" class="flag-progress-ring" aria-hidden="true">
                                <circle class="flag-progress-track" cx="40" cy="40" r="34" pathLength="100"/>
                                <circle class="flag-progress-bar" id="flag-progress-bar" cx="40" cy="40" r="34" pathLength="100"/>
                            </svg>
                            <span class="flag-progress-label" id="flag-progress-label">0/0</span>
                        </div>
                    </div>
                    <div class="flag-form">
                        <input type="text" id="flag-input" placeholder="Enter flag..." class="flag-input">
                        <button id="submit-flag" class="button button-primary">
                            <span class="button-icon">🏴</span> Submit
                        </button>
                    </div>
                    <div id="flag-feedback" class="flag-feedback"></div>
                </div>
            </div>
        </div>
        <div class="leaderboard-section">
            <div class="leaderboard-header">
                <h3 class="leaderboard-title">Leaderboard</h3>
                <button class="leaderboard-refresh">
                    <i class="icon-refresh"></i> Refresh
                </button>
            </div>

            <table class="leaderboard-table">
                <thead>
                <tr>
                    <th>Rank</th>
                    <th>User</th>
                    <th>Time</th>
                </tr>
                </thead>
                <tbody id="leaderboard-content">
                <!-- This will be populated by JavaScript -->
                </tbody>
            </table>
        </div>
    </main>
</div>
<?php include($_SERVER['DOCUMENT_ROOT'] . '/partials/footer.html'); ?>

<script type="module" src="../assets/js/challenge.js"></script>
<script type="module" src="../assets/js/theme-toggle.js"></script>
</body>
</html>