<?php
require_once __DIR__ . '/../vendor/autoload.php';
$securityHelper = new SecurityHelper();
$securityHelper->initSecureSession();
$csrf_token = $securityHelper->generateCsrfToken();
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sign Up - heiST</title>
    <link rel="icon" type="image/svg+xml" href="/assets/icons/favicon.svg">
    <link rel="stylesheet" href="../assets/css/base.css">
    <link rel="stylesheet" href="../assets/css/login.css">
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
<div class="logo-container">
    <a href="/landing">
        <img id="logo-img" src="/assets/icons/logo_dark.svg" alt="heiST" class="logo-icon" />
    </a>
</div>
<div class="login-container">
    <form class="login-form" id="signupForm" method="POST">
        <input type="hidden" name="csrf_token" value="<?php echo (new SecurityHelper())->generateCsrfToken();?>">
        <h2>Sign Up</h2>
        <div class="input-group has-icon">
            <label for="username">Username (Uni-ID)</label>
            <div class="input-wrapper">
                <input type="text" id="username" name="username" placeholder="Enter your Uni-ID" required>
                <i class="fa-solid fa-circle-exclamation input-error-icon" id="username-icon"></i>
            </div>
            <small class="error-message" id="username-error"></small>
        </div>
        <div class="input-group has-icon">
            <label for="email">Email (Same as registered in Moodle)</label>
            <div class="input-wrapper">
                <input type="email" id="email" name="email" placeholder="Enter your moodle email" required>
                <i class="fa-solid fa-circle-exclamation input-error-icon" id="email-icon"></i>
            </div>
            <small class="error-message" id="email-error"></small>
        </div>
        <div class="input-group password-container has-icon">
            <label for="password">Password</label>
            <div class="password-wrapper input-wrapper">
                <input type="password" id="password" name="password" placeholder="Enter your password" required>
                <button type="button" class="password-toggle" aria-label="Toggle password visibility">
                    <i class="fa-solid fa-eye"></i>
                </button>
                <i class="fa-solid fa-circle-exclamation input-error-icon" id="password-icon"></i>
            </div>
            <small class="error-message" id="password-error"></small>
        </div>
        <div class="input-group password-container has-icon">
            <label for="confirm-password">Confirm Password</label>
            <div class="password-wrapper input-wrapper">
                <input type="password" id="confirm-password" name="confirm-password" placeholder="Confirm your password"
                       required>
                <button type="button" class="password-toggle" aria-label="Toggle password visibility">
                    <i class="fa-solid fa-eye"></i>
                </button>
                <i class="fa-solid fa-circle-exclamation input-error-icon" id="confirm-password-icon"></i>
            </div>
            <small class="error-message" id="confirm-password-error"></small>
        </div>
        <div class="input-group has-icon">
            <label for="token">Token</label>
            <div class="input-wrapper">
                <input type="text" id="token" name="token" placeholder="Enter your token" required>
                <i class="fa-solid fa-circle-exclamation input-error-icon" id="token-icon"></i>
            </div>
            <small class="error-message" id="token-error"></small>
        </div>
        <div class="input-group tos">
            <label class="remember-me tos-label">
                <div>
                    <input type="checkbox" id="agree-tos" name="agree_tos">
                    <span class="custom-checkbox"></span>
                </div>
                <div>
                    I have read and agree to the
                    <a href="/terms-of-service" target="_blank" class="tos-link">Terms of Service</a>
                    and
                    <a href="/privacy-policy" target="_blank" class="tos-link">Privacy Policy</a>
                </div>
            </label>
        </div>
        <button type="submit" class="button button-primary">Sign Up</button>
        <div class="form-feedback" id="form-feedback"></div>
        <p class="create-account">
            Already have an account? <a href="/login">Login</a>
        </p>
    </form>
</div>
<?php include($_SERVER['DOCUMENT_ROOT'] . '/partials/footer.html'); ?>
<script type="module" src="../assets/js/theme-toggle.js"></script>
<script type="module" src="../assets/js/signup.js"></script>
<script type="module" src="../assets/js/logo-toggle.js"></script>
</body>
</html>
