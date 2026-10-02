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
    <title>Login - heiST</title>
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
    <form class="login-form" id="loginForm" method="POST">
        <input type="hidden" name="csrf_token" id="csrf_token"
               value="<?php echo htmlspecialchars($_SESSION['csrf_token'] ?? '', ENT_QUOTES); ?>">
        <h2>Login</h2>

        <div class="input-group has-icon">
            <label for="username">Username</label>
            <div class="input-wrapper">
                <input type="text" id="username" name="username" placeholder="Enter your username" required>
                <i class="fa-solid fa-circle-exclamation input-error-icon" id="username-icon"></i>
            </div>
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

        <div class="login-options">
            <label class="remember-me">
                <input type="checkbox" id="remember-me">
                <span class="custom-checkbox"></span>
                Remember Me
            </label>
            <a href="#" class="forgot-password">Forgot Password?</a>
        </div>
        <button type="submit" class="button button-primary">Login</button>
        <div class="form-feedback" id="form-feedback"></div>
        <p class="create-account">
            New to heiST? <a href="/signup">Create Account</a>
        </p>
    </form>
</div>
<?php include($_SERVER['DOCUMENT_ROOT'] . '/partials/footer.html'); ?>
<script type="module" src="../assets/js/theme-toggle.js"></script>
<script type="module" src="../assets/js/login.js"></script>
<script type="module" src="../assets/js/logo-toggle.js"></script>
</body>
</html>
