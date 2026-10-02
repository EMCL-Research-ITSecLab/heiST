<?php
declare(strict_types=1);
require_once __DIR__ . '/../vendor/autoload.php';

$securityHelper = new SecurityHelper();
$securityHelper->initSecureSession();

if (!$securityHelper->validateSession()) {
    header('Location: /404');
    exit();
}

if (!$securityHelper->requiresPasswordChange()) {
    header('Location: /dashboard');
    exit();
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reset Password - heiST</title>
    <link rel="icon" type="image/svg+xml" href="/assets/icons/favicon.svg">
    <link rel="stylesheet" href="../assets/css/base.css">
    <link rel="stylesheet" href="../assets/css/reset-password.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body>
<div class="theme-switch">
    <label class="switch">
        <input type="checkbox" id="theme-toggle">
        <span class="slider">
            <img class="icon moon" src="/assets/icons/moon.svg"/>
            <img class="icon sun" src="/assets/icons/sun.svg"/>
        </span>
    </label>
</div>
<div class="reset-password-logo">
    <a href="/landing">heiST</a>
</div>
<div class="reset-password-container">
    <form class="reset-password-form" id="resetPasswordForm" method="POST">
        <h2>Reset Password</h2>

        <!-- Current Password -->
        <div class="input-group password-container has-icon">
            <label for="current-password">Current Password</label>
            <div class="password-wrapper input-wrapper">
                <input type="password" id="current-password" name="current_password"
                       placeholder="Enter your current password" required>
                <button type="button" class="password-toggle" aria-label="Toggle password visibility">
                    <i class="fa-solid fa-eye"></i>
                </button>
                <i class="fa-solid fa-circle-exclamation input-error-icon" id="current-password-icon"></i>
            </div>
            <small class="error-message" id="current-password-error"></small>
        </div>

        <!-- New Password -->
        <div class="input-group password-container has-icon">
            <label for="new-password">New Password</label>
            <div class="password-wrapper input-wrapper">
                <input type="password" id="new-password" name="new_password"
                       placeholder="Enter your new password" required>
                <button type="button" class="password-toggle" aria-label="Toggle password visibility">
                    <i class="fa-solid fa-eye"></i>
                </button>
                <i class="fa-solid fa-circle-exclamation input-error-icon" id="new-password-icon"></i>
            </div>
            <small class="error-message" id="new-password-error"></small>
        </div>

        <!-- Confirm New Password -->
        <div class="input-group password-container has-icon">
            <label for="confirm-password">Confirm New Password</label>
            <div class="password-wrapper input-wrapper">
                <input type="password" id="confirm-password" name="confirm_password"
                       placeholder="Confirm your new password" required>
                <button type="button" class="password-toggle" aria-label="Toggle password visibility">
                    <i class="fa-solid fa-eye"></i>
                </button>
                <i class="fa-solid fa-circle-exclamation input-error-icon" id="confirm-password-icon"></i>
            </div>
            <small class="error-message" id="confirm-password-error"></small>
        </div>

        <button type="submit" class="button button-primary">Update Password</button>

        <!-- Form Feedback Area -->
        <div class="form-feedback" id="form-feedback"></div>

        <p class="back-link">
            <a href="/dashboard">Back to Dashboard</a>
        </p>
    </form>
</div>
<?php include($_SERVER['DOCUMENT_ROOT'] . '/partials/footer.html'); ?>
<script type="module" src="../assets/js/theme-toggle.js"></script>
<script type="module" src="../assets/js/reset-password.js"></script>
</body>
</html>