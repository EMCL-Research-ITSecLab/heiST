class SignupForm {
    constructor() {
        this.config = null;
        this.form = document.querySelector('.login-form');
        this.passwordToggles = document.querySelectorAll('.password-toggle');
        this.submitButton = this.form?.querySelector('button[type="submit"]');
        this.formFeedback = document.getElementById('form-feedback');
        this.originalButtonText = this.submitButton?.textContent;

        this.errorMapping = {
            'Username': 'username',
            'Email': 'email',
            'Password': 'password',
            'Confirm Password': 'confirm-password',
            'Token': 'token',
            'Terms': 'agree-tos'
        };

        this.loadConfig().then(() => {
            this.init();
        });
    }

    init() {
        if (!this.form) return;

        this.hideErrorIcons();
        this.setupPasswordToggles();
        this.setupFormSubmission();
        this.setupRealTimeValidation();
        this.setupTosValidation();
    }

    async loadConfig() {
        try {
            const response = await fetch('/config/general.config.json');
            const config = await response.json();
            this.config = config.user;

            this.config.USERNAME_REGEX = new RegExp(this.config.USERNAME_REGEX);
            this.config.EMAIL_REGEX = new RegExp(this.config.EMAIL_REGEX);
        } catch (error) {
            console.error('Failed to load config:', error);
        }
    }

    setupTosValidation() {
        const tosCheckbox = document.getElementById('agree-tos');
        if (!tosCheckbox) return;

        tosCheckbox.addEventListener('change', () => {
            if (tosCheckbox.checked) {
                this.clearTosError();
            }
        });
    }

    setupRealTimeValidation() {
        const usernameField = this.form.querySelector('#username');
        const emailField = this.form.querySelector('#email');
        const passwordField = this.form.querySelector('#password');
        const confirmPasswordField = this.form.querySelector('#confirm-password');
        const tokenField = this.form.querySelector('#token');

        if (usernameField) {
            usernameField.addEventListener('blur', () => this.validateUsername(usernameField.value));
        }

        if (emailField) {
            emailField.addEventListener('blur', () => this.validateEmail(emailField.value));
        }

        if (passwordField) {
            passwordField.addEventListener('blur', () => this.validatePassword(passwordField.value));
        }

        if (confirmPasswordField) {
            confirmPasswordField.addEventListener('blur', () => {
                if (passwordField) {
                    this.validatePasswordMatch(passwordField.value, confirmPasswordField.value);
                }
            });
        }

        if (tokenField) {
            tokenField.addEventListener('blur', () => this.validateToken(tokenField.value));
        }
    }

    validateUsername(username) {
        if (!username) {
            this.showError('username', 'Username is required');
            return false;
        }

        if (username.length < this.config.MIN_USERNAME_LENGTH) {
            this.showError('username', `Username must be at least ${this.config.MIN_USERNAME_LENGTH} characters`);
            return false;
        }

        if (username.length > this.config.MAX_USERNAME_LENGTH) {
            this.showError('username', `Username cannot exceed ${this.config.MAX_USERNAME_LENGTH} characters`);
            return false;
        }

        if (!this.config.USERNAME_REGEX.test(username)) {
            this.showError('username', 'Username can only contain letters, numbers, and underscores');
            return false;
        }

        this.clearError('username');
        return true;
    }

    validateEmail(email) {
        if (!email) {
            this.showError('email', 'Email is required');
            return false;
        }

        if (email.length > this.config.MAX_EMAIL_LENGTH) {
            this.showError('email', `Email cannot exceed ${this.config.MAX_EMAIL_LENGTH} characters`);
            return false;
        }

        if (!this.config.EMAIL_REGEX.test(email)) {
            this.showError('email', 'Please enter a valid email address');
            return false;
        }

        this.clearError('email');
        return true;
    }

    validatePassword(password) {
        if (!password) {
            this.showError('password', 'Password is required');
            return false;
        }

        if (password.length < this.config.MIN_PASSWORD_LENGTH) {
            this.showError('password', `Password must be at least ${this.config.MIN_PASSWORD_LENGTH} characters`);
            return false;
        }

        if (password.length > this.config.MAX_PASSWORD_LENGTH) {
            this.showError('password', `Password cannot exceed ${this.config.MAX_PASSWORD_LENGTH} characters`);
            return false;
        }

        this.clearError('password');
        return true;
    }

    validatePasswordMatch(password, confirmPassword) {
        if (password !== confirmPassword) {
            this.showError('confirm-password', 'Passwords do not match');
            return false;
        }

        this.clearError('confirm-password');
        return true;
    }

    validateToken(token) {
        if (!token) {
            this.showError('token', 'Token is required');
            return false;
        }

        this.clearError('token');
        return true;
    }

    validateTos() {
        const tosCheckbox = document.getElementById('agree-tos');
        if (!tosCheckbox) return true;

        if (!tosCheckbox.checked) {
            this.showTosError('You must agree to the Terms of Service and Privacy Policy');
            return false;
        }

        this.clearTosError();
        return true;
    }

    showTosError(message) {
        const tosCheckbox = document.getElementById('agree-tos');
        if (!tosCheckbox) return;

        const customCheckbox = tosCheckbox.parentElement?.querySelector('.custom-checkbox');

        if (customCheckbox) {
            customCheckbox.style.borderColor = '#ff6b6b';
            customCheckbox.style.border = '2px solid #ff6b6b';
        }

        // Scroll to checkbox so user sees it
        tosCheckbox.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    clearTosError() {
        const tosCheckbox = document.getElementById('agree-tos');
        if (!tosCheckbox) return;

        const customCheckbox = tosCheckbox.parentElement?.querySelector('.custom-checkbox');

        if (customCheckbox) {
            customCheckbox.style.borderColor = '';
            customCheckbox.style.border = '';
        }
    }


    clearError(fieldId) {
        const field = document.getElementById(fieldId);
        if (!field) return;

        const inputGroup = field.closest('.input-group');
        const errorElement = inputGroup?.querySelector('.error-message');
        const iconElement = inputGroup?.querySelector('.input-error-icon');

        if (errorElement && iconElement) {
            field.classList.remove('error');
            errorElement.textContent = '';
            iconElement.style.display = 'none';
        }
    }

    setupFormSubmission() {
        this.form.addEventListener('submit', async (e) => {
            e.preventDefault();
            this.resetErrorStates();

            const username = this.form.querySelector('#username')?.value;
            const email = this.form.querySelector('#email')?.value;
            const password = this.form.querySelector('#password')?.value;
            const confirmPassword = this.form.querySelector('#confirm-password')?.value;
            const token = this.form.querySelector('#token')?.value;

            const isUsernameValid = this.validateUsername(username);
            const isEmailValid = this.validateEmail(email);
            const isPasswordValid = this.validatePassword(password);
            const isPasswordMatchValid = this.validatePasswordMatch(password, confirmPassword);
            const isTokenValid = this.validateToken(token);
            const isTosValid = this.validateTos();

            if (!isUsernameValid || !isEmailValid || !isPasswordValid || !isPasswordMatchValid || !isTokenValid || !isTosValid) {
                return;
            }

            try {
                this.setLoadingState(true);
                const response = await this.submitForm();
                const data = await response.json();

                if (data.success) {
                    window.location.href = '/dashboard';
                } else {
                    this.handleFormError(data);
                }
            } catch (error) {
                this.displayGeneralError('An error occurred. Please try again.');
                console.error('Error:', error);
            } finally {
                this.setLoadingState(false);
            }
        });
    }

    hideErrorIcons() {
        document.querySelectorAll('.input-error-icon').forEach(icon => {
            icon.style.display = 'none';
        });
    }

    setupPasswordToggles() {
        this.passwordToggles.forEach(toggle => {
            const passwordInput = toggle.previousElementSibling;
            toggle.addEventListener('click', () => this.togglePasswordVisibility(passwordInput, toggle));
        });
    }

    togglePasswordVisibility(input, toggle) {
        if (input.type === 'password') {
            input.type = 'text';
            toggle.innerHTML = '<i class="fa-solid fa-eye-slash"></i>';
        } else {
            input.type = 'password';
            toggle.innerHTML = '<i class="fa-solid fa-eye"></i>';
        }
    }

    async submitForm() {
        const formData = new FormData(this.form);
        return await fetch('../backend/signup.php', {
            method: 'POST',
            body: formData
        });
    }

    setLoadingState(isLoading) {
        if (!this.submitButton) return;

        this.submitButton.disabled = isLoading;
        this.submitButton.textContent = isLoading ? 'Signing Up...' : this.originalButtonText;
    }

    handleFormError(data) {
        this.displayGeneralError(data.message || 'Registration failed');

        let fieldFound = false;
        for (const [keyword, fieldId] of Object.entries(this.errorMapping)) {
            if (data.message.toLowerCase().includes(keyword.toLowerCase())) {
                if (fieldId === 'agree-tos') {
                    this.showTosError(data.message);
                } else {
                    this.showError(fieldId, data.message);
                }

                fieldFound = true;
                if (keyword === 'Password') {
                    this.showError('confirm-password', data.message);
                }
            }
        }

        if (!fieldFound) {
            this.showError('username', data.message);
        }
    }

    displayGeneralError(message) {
        if (!this.formFeedback) return;

        this.formFeedback.textContent = message;
        this.formFeedback.className = 'form-feedback error';
    }

    showError(fieldId, message) {
        const field = document.getElementById(fieldId);
        if (!field) return;

        const inputGroup = field.closest('.input-group');
        const errorElement = inputGroup?.querySelector('.error-message');
        const iconElement = inputGroup?.querySelector('.input-error-icon');

        if (errorElement && iconElement) {
            field.classList.add('error');
            errorElement.textContent = message;
            iconElement.style.display = 'block';
            errorElement.style.display = 'block';
            errorElement.style.visibility = 'visible';
            errorElement.style.opacity = '1';
            errorElement.style.setProperty('background-color', 'transparent', 'important');
        }
    }

    resetErrorStates() {
        document.querySelectorAll('.input-group input').forEach(field => {
            field.classList.remove('error');
        });

        document.querySelectorAll('.input-error-icon').forEach(icon => {
            icon.style.display = 'none';
        });

        document.querySelectorAll('.error-message').forEach(msg => {
            msg.textContent = '';
            msg.style.display = 'none';
            msg.style.visibility = 'hidden';
            msg.style.opacity = '0';
        });

        if (this.formFeedback) {
            this.formFeedback.textContent = '';
            this.formFeedback.className = 'form-feedback';
        }

        this.clearTosError();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new SignupForm();
});