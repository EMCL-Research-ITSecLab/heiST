<?php
declare(strict_types=1);

require_once __DIR__ . '/../vendor/autoload.php';

class ProfileHandler
{
    private PDO $pdo;
    private ?int $userId;
    private string $requestMethod;
    private array $generalConfig;
    private string $route;

    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ILogger $logger;
    private IAuthHelper $authHelper;
    private ICurlHelper $curlHelper;

    private ISession $session;
    private IServer $server;
    private IGet $get;
    private IPost $post;
    private IFiles $files;
    private IEnv $env;
    private ICookie $cookie;

    private ISystem $system;

    /**
     * @throws Exception
     */
    public function __construct(
        array $generalConfig,
        
        IDatabaseHelper $databaseHelper = null,
        ISecurityHelper $securityHelper = null,
        ILogger $logger = null,
        IAuthHelper $authHelper = null,
        ICurlHelper $curlHelper = null,
        
        ISession $session = new Session(),
        IServer $server = new Server(),
        IGet $get = new Get(),
        IPost $post = new Post(),
        IFiles $files = new Files(),
        IEnv $env = new Env(),
        
        ISystem $system = new SystemWrapper(),
        ICookie $cookie = new Cookie()
    )
    {
        $this->session = $session;
        $this->server = $server;
        $this->get = $get;
        $this->post = $post;
        $this->files = $files;
        $this->env = $env;
        $this->cookie = $cookie;
        $this->route = "/profile";

        $this->databaseHelper = $databaseHelper ?? new DatabaseHelper($logger, $system);
        $this->securityHelper = $securityHelper ?? new SecurityHelper($logger, $session, $system);
        $this->logger = $logger ?? new Logger(route: $this->route, system: $system);
        $this->authHelper = $authHelper ?? new AuthHelper($logger, $system, $env);
        $this->curlHelper = $curlHelper ?? new CurlHelper($env);

        $this->system = $system;

        $this->generalConfig = $generalConfig;
        $this->pdo = $this->databaseHelper->getPDO();
        $this->initSession();
        $this->validateSession();
        $this->requestMethod = $this->server['REQUEST_METHOD'];
        $this->logger->logDebug("Initialized ProfileHandler for user ID: $this->userId");
    }

    private function initSession(): void
    {
        $this->securityHelper->initSecureSession();
    }

    /**
     * @throws Exception
     */
    private function validateSession(): void
    {
        if (!$this->securityHelper->validateSession()) {
            $this->logger->logWarning("Unauthorized access attempt to profile - IP: " . $this->logger->anonymizeIp($this->server['REMOTE_ADDR'] ?? 'unknown'));
            throw new CustomException('Unauthorized - Please login', 401);
        }
        $this->userId = (int)$this->session['user_id'];
        $csrfToken = $this->cookie['csrf_token'] ?? '';
        if (!$this->securityHelper->validateCsrfToken($csrfToken)) {
            $this->logger->logWarning("Invalid CSRF token in profile request - User ID: $this->userId, Token: $csrfToken");
            throw new CustomException('Invalid CSRF token', 403);
        }
    }

    public function handleRequest(): void
    {
        try {
            switch ($this->requestMethod) {
                case 'GET':
                    $this->handleGetRequest();
                    break;
                case 'POST':
                    $this->handlePostRequest();
                    break;
                case 'DELETE':
                    $this->handleDeleteRequest();
                    break;
                default:
                    $this->logger->logWarning("Invalid method in profile request - Method: $this->requestMethod, User ID: $this->userId");
                    throw new CustomException('Method not allowed', 405);
            }
        } catch (CustomException $e) {
            $this->handleError($e);
        } // @codeCoverageIgnoreStart
        catch (Exception $e) {
            // most likely not reachable, gonna leave it here for safety
            $this->handleError(new Exception('Internal Server Error', 500));
        }
        // @codeCoverageIgnoreEnd
    }

    /**
     * @throws Exception
     */
    private function handleGetRequest(): void
    {
        $dataType = $this->get['type'] ?? 'full';

        if (!in_array($dataType, ['basic', 'stats', 'badges', 'activity', 'full'])) {
            $this->logger->logWarning("Invalid data type requested - Type: $dataType, User ID: $this->userId");
            throw new CustomException('Invalid data type requested', 400);
        }

        $response = match ($dataType) {
            'basic' => $this->getBasicProfileData(),
            'stats' => $this->getProfileStats(),
            'badges' => $this->getProfileBadges(),
            'activity' => $this->getRecentActivity(),
            default => [
                'basic' => $this->getBasicProfileData(),
                'stats' => $this->getProfileStats(),
                'badges' => $this->getProfileBadges(),
                'activity' => $this->getRecentActivity()
            ],
        };
        $this->sendResponse(['success' => true, 'data' => $response]);
    }

    /**
     * @throws RandomException
     * @throws Exception
     */
    private function handlePostRequest(): void
    {
        $contentType = $this->server['CONTENT_TYPE'] ?? '';
        $isJson = str_contains($contentType, 'application/json');

        if ($isJson) {
            $json = $this->system->file_get_contents('php://input');
            $data = json_decode($json, true);
            if (json_last_error() !== JSON_ERROR_NONE) {
                $this->logger->logWarning("Invalid JSON in profile update - User ID: $this->userId");
                throw new CustomException('Invalid JSON data', 400);
            }
        } else {
            $data = $this->post->all();
        }

        $action = $data['action'] ?? '';
        switch ($action) {
            case 'update_username':
                $this->validateUsername($data['username'] ?? '');
                $this->updateUsername($data['username']);
                break;
            case 'update_email':
                $this->validateEmail($data['email'] ?? '');
                $this->updateEmail($data['email']);
                break;
            case 'update_full_name':
                $this->validateFullName($data['full_name'] ?? '');
                $this->updateFullName($data['full_name']);
                break;
            case 'update_bio':
                $this->validateBio($data['bio'] ?? '');
                $this->updateBio($data['bio']);
                break;
            case 'update_social':
                $this->validateSocialLinks([
                    'github' => $data['github'] ?? '',
                    'twitter' => $data['twitter'] ?? '',
                    'website' => $data['website'] ?? ''
                ]);
                $this->updateSocialLinks([
                    'github' => $data['github'],
                    'twitter' => $data['twitter'],
                    'website' => $data['website']
                ]);
                break;
            case 'upload_avatar':
                $this->handleAvatarUpload();
                break;
            case 'update_avatar':
                $this->validateAvatarSelection($data['avatar'] ?? '');
                $this->handleAvatarUpdate();
                break;
            case 'change_password':
                $this->validatePasswordChange(
                    $data['current_password'] ?? '',
                    $data['new_password'] ?? ''
                );
                $this->changePassword($data['current_password'], $data['new_password']);
                break;
            case 'get_vpn_config':
                $this->handleVpnConfigDownload();
                break;
            case 'update_ai_consent':
                $consent = filter_var($data['consent'] ?? true, FILTER_VALIDATE_BOOLEAN);
                $this->updateAiConsent($consent);
                break;
            default:
                $this->logger->logWarning("Invalid action in profile update - Action: $action, User ID: $this->userId");
                throw new CustomException('Invalid action specified', 400);
        }
    }

    /**
     * @throws Exception
     */
    private function validateUsername(string $username): void
    {
        if (empty($username)) {
            throw new CustomException('Username cannot be empty', 400);
        }
        if (strlen($username) < $this->generalConfig['user']['MIN_USERNAME_LENGTH'] || strlen($username) > $this->generalConfig['user']['MAX_USERNAME_LENGTH']) {
            throw new CustomException(sprintf('Username must be between %d and %d characters',
                $this->generalConfig['user']['MIN_USERNAME_LENGTH'], $this->generalConfig['user']['MAX_USERNAME_LENGTH']), 400);
        }
        if (!preg_match('/' . $this->generalConfig['user']['USERNAME_REGEX'] . '/', $username)) {
            throw new CustomException('Username can only contain letters, numbers and underscores', 400);
        }
    }

    /**
     * @throws Exception
     */
    private function validateEmail(string $email): void
    {
        if (empty($email)) {
            throw new CustomException('Email cannot be empty', 400);
        }
        if (strlen($email) > $this->generalConfig['user']['MAX_EMAIL_LENGTH']) {
            throw new CustomException('Email is too long', 400);
        }
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
            throw new CustomException('Invalid email format', 400);
        }
    }

    /**
     * @throws Exception
     */
    private function validateFullName(string $fullName): void
    {
        if (empty($fullName)) {
            throw new CustomException('Full name cannot be empty', 400);
        }
        if (strlen($fullName) < $this->generalConfig['user']['MIN_FULL_NAME_LENGTH'] || strlen($fullName) > $this->generalConfig['user']['MAX_FULL_NAME_LENGTH']) {
            throw new CustomException(sprintf('Name must be between %d and %d characters',
                $this->generalConfig['user']['MIN_FULL_NAME_LENGTH'], $this->generalConfig['user']['MAX_FULL_NAME_LENGTH']), 400);
        }
        if (!preg_match('/' . $this->generalConfig['user']['FULL_NAME_REGEX'] . '/u', $fullName)) {
            throw new CustomException('Name contains invalid characters. Name must include at least a first and last name, starting with capital letters.', 400);
        }
    }

    /**
     * @throws Exception
     */
    private function validateBio(string $bio): void
    {
        if (strlen($bio) > $this->generalConfig['user']['MAX_BIO_LENGTH']) {
            throw new CustomException(sprintf('Bio cannot exceed %d characters', $this->generalConfig['user']['MAX_BIO_LENGTH']), 400);
        }
    }

    /**
     * @throws Exception
     */
    private function validateSocialLinks(array $links): void
    {
        foreach ($links as $type => $url) {
            $url = trim($url);

            if (!empty($url) && strlen($url) > $this->generalConfig['user']['MAX_SOCIAL_URL_LENGTH']) {
                throw new CustomException(sprintf('%s URL is too long', ucfirst($type)), 400);
            }

            if (empty($url)) {
                continue;
            }

            if (!filter_var($url, FILTER_VALIDATE_URL)) {
                throw new CustomException(sprintf('Invalid %s URL', $type), 400);
            }

            switch ($type) {
                case 'github':
                    if (!preg_match('/' . $this->generalConfig['user']['GITHUB_REGEX'] . '/', $url)) {
                        throw new CustomException('GitHub URL must be in the format https://github.com/username', 400);
                    }
                    break;

                case 'twitter':
                    if (!preg_match('/' . $this->generalConfig['user']['TWITTER_REGEX'] . '/', $url)) {
                        throw new CustomException('Twitter URL must be in the format https://twitter.com/username or https://x.com/username', 400);
                    }
                    break;

                case 'website':
                    break;

                default:
                    throw new CustomException(sprintf('Unknown social link type: %s', $type), 400);
            }
        }
    }

    /**
     * @throws Exception
     */
    private function validatePasswordChange(string $currentPassword, string $newPassword): void
    {
        if (empty($currentPassword) || empty($newPassword)) {
            throw new CustomException('Both current and new password are required', 400);
        }
        if (strlen($newPassword) < $this->generalConfig['user']['MIN_PASSWORD_LENGTH']) {
            throw new CustomException(sprintf('Password must be at least %d characters', $this->generalConfig['user']['MIN_PASSWORD_LENGTH']), 400);
        }
        if (strlen($newPassword) > $this->generalConfig['user']['MAX_PASSWORD_LENGTH']) {
            throw new CustomException(sprintf('Password cannot exceed %d characters', $this->generalConfig['user']['MAX_PASSWORD_LENGTH']), 400);
        }
    }

    /**
     * @throws Exception
     */
    private function validateAvatarSelection(string $avatar): void
    {
        $allowedAvatars = ['avatar1', 'avatar2', 'avatar3'];
        if (!in_array($avatar, $allowedAvatars)) {
            throw new CustomException('Invalid avatar selection', 400);
        }
    }

    private function getBasicProfileData(): array
    {
        try {
            $stmt = $this->pdo->prepare("
                SELECT 
                    username,
                    email,
                    created_at,
                    last_login,
                    avatar_url,
                    full_name,
                    bio,
                    github_url,
                    twitter_url,
                    website_url,
                    solved_count,
                    total_points,
                    ai_training_consent
                FROM get_basic_profile_data(:user_id)
            ");
            $stmt->execute(['user_id' => $this->userId]);
            $profileData = $stmt->fetch(PDO::FETCH_ASSOC);

            if (!$profileData) {
                $this->logger->logError("Profile not found - User ID: $this->userId");
                throw new CustomException('User profile not available', 404);
            }

            $rankStmt = $this->pdo->prepare("
                SELECT get_user_rank(:user_id, :user_points) AS user_rank
            ");
            $rankStmt->execute([
                'user_id' => $this->userId,
                'user_points' => $profileData['total_points']
            ]);
            $rankData = $rankStmt->fetch(PDO::FETCH_ASSOC);

            $lastLogin = 'Never';
            if ($profileData['last_login'] && $profileData['last_login'] !== '0000-00-00 00:00:00') {
                try {
                    $lastLogin = (new DateTime($profileData['last_login']))->format('F j, Y \a\t g:i A');
                } catch (CustomException) {
                    $this->logger->logError("Invalid last login date format - User ID: $this->userId, Date: {$profileData['last_login']}");
                    $lastLogin = 'Unknown';
                } catch (Exception) {
                    $this->logger->logError("Invalid last login date format - User ID: $this->userId, Date: {$profileData['last_login']}");
                    $lastLogin = 'Unknown';
                }
            }

            return [
                'username' => htmlspecialchars($profileData['username'], ENT_QUOTES, 'UTF-8'),
                'email' => filter_var($profileData['email'], FILTER_SANITIZE_EMAIL),
                'join_date' => $profileData['created_at'],
                'last_login' => $lastLogin,
                'avatar_url' => filter_var($profileData['avatar_url'] ?? '/assets/avatars/default-avatar.png', FILTER_SANITIZE_URL),
                'full_name' => htmlspecialchars($profileData['full_name'] ?? '', ENT_QUOTES, 'UTF-8'),
                'bio' => htmlspecialchars($profileData['bio'] ?? '', ENT_QUOTES, 'UTF-8'),
                'social_links' => [
                    'github' => filter_var($profileData['github_url'] ?? '', FILTER_SANITIZE_URL),
                    'twitter' => filter_var($profileData['twitter_url'] ?? '', FILTER_SANITIZE_URL),
                    'website' => filter_var($profileData['website_url'] ?? '', FILTER_SANITIZE_URL)
                ],
                'rank' => (int)($rankData['user_rank'] ?? 1),
                'points' => (int)$profileData['total_points'],
                'solved_count' => (int)$profileData['solved_count'],
                'ai_training_consent' => (bool)$profileData['ai_training_consent']
            ];

        } catch (PDOException $e) {
            $this->logger->logError("Database error in getBasicProfileData - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to retrieve profile data', 500);
        }
    }


    /**
     * @throws Exception
     */
    private function updateAiConsent(bool $consent): void
    {
        $this->pdo->beginTransaction();
        try {
            $stmt = $this->pdo->prepare("SELECT update_ai_training_consent(:user_id, :consent)");
            $stmt->bindValue(':consent', $consent, PDO::PARAM_BOOL);
            $stmt->bindValue(':user_id', $this->userId, PDO::PARAM_INT);
            $stmt->execute();

            $this->pdo->commit();
            $this->logger->logDebug("AI training consent updated - User ID: $this->userId, Consent: " . ($consent ? 'true' : 'false'));

            $this->sendResponse([
                'success' => true,
                'message' => 'Privacy preferences updated successfully',
                'ai_training_consent' => $consent
            ]);

        } catch (PDOException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Database error during AI consent update - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to update privacy preferences', 500);
        }
    }

    private function getProfileStats(): array
    {
        try {
            $stmt = $this->pdo->prepare("
                SELECT 
                    solved,
                    attempts,
                    total_points
                FROM get_profile_stats(:user_id)
            ");
            $stmt->execute(['user_id' => $this->userId]);
            $statsData = $stmt->fetch(PDO::FETCH_ASSOC);

            if (!$statsData) {
                $this->logger->logError("Failed to retrieve profile stats - User ID: $this->userId");
                throw new CustomException('Failed to retrieve profile statistics', 500);
            }

            $successRate = 0;
            if ($statsData['attempts'] > 0) {
                $successRate = round(($statsData['solved'] / $statsData['attempts']) * 100);
            }

            $categoryData = $this->getCategoryData();

            return [
                'categories' => array_map('htmlspecialchars', $categoryData['categories']),
                'percentages' => array_map('intval', $categoryData['percentages']),
                'solved_counts' => array_map('intval', $categoryData['solved_counts']),
                'success_rate' => $successRate,
                'total_solved' => (int)$statsData['solved'],
                'total_points' => (int)$statsData['total_points'],
                'total_attempts' => (int)$statsData['attempts']
            ];

        } catch (PDOException $e) {
            $this->logger->logError("Database error in getProfileStats - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to retrieve profile statistics', 500);
        }
    }

    private function getProfileBadges(): array
    {
        try {
            $stmt = $this->pdo->prepare("
                SELECT 
                    id,
                    name,
                    description,
                    icon,
                    color
                FROM get_profile_badges(:user_id)
            ");
            $stmt->execute(['user_id' => $this->userId]);
            $badges = $stmt->fetchAll(PDO::FETCH_ASSOC);

            $sanitizedBadges = array_map(function ($badge) {
                return [
                    'id' => (int)$badge['id'],
                    'name' => htmlspecialchars($badge['name'], ENT_QUOTES, 'UTF-8'),
                    'description' => htmlspecialchars($badge['description'], ENT_QUOTES, 'UTF-8'),
                    'icon' => $badge['icon'],
                    'color' => $badge['color']
                ];
            }, $badges);

            $totalStmt = $this->pdo->query("SELECT get_total_badges_count() AS total");
            $totalBadges = (int)$totalStmt->fetch(PDO::FETCH_ASSOC)['total'];

            $earnedCount = count($sanitizedBadges);

            return [
                'badges' => $sanitizedBadges,
                'earned_count' => $earnedCount,
                'total_badges' => $totalBadges
            ];

        } catch (PDOException $e) {
            $this->logger->logError("Database error in getProfileBadges - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to retrieve badge information', 500);
        }
    }

    private function getRecentActivity(int $limit = 5): array
    {
        try {
            if ($limit < 1 || $limit > 50) {
                $limit = 5;
            }

            $stmt = $this->pdo->prepare("
                SELECT 
                    challenge_id,
                    challenge_name,
                    category,
                    points,
                    solved,
                    attempts,
                    started_at,
                    completed_at,
                    status,
                    time_ago
                FROM get_recent_activity(:user_id, :limit)
            ");
            $stmt->bindValue(':user_id', $this->userId, PDO::PARAM_INT);
            $stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
            $stmt->execute();

            $activities = [];
            while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
                $activities[] = [
                    'challenge_id' => (int)$row['challenge_id'],
                    'challenge_name' => htmlspecialchars($row['challenge_name'], ENT_QUOTES, 'UTF-8'),
                    'category' => htmlspecialchars($row['category'], ENT_QUOTES, 'UTF-8'),
                    'points' => (int)$row['points'],
                    'status' => $row['status'],
                    'attempts' => (int)$row['attempts'],
                    'time_ago' => $row['time_ago'],
                    'started_at' => $row['started_at'],
                    'completed_at' => $row['completed_at']
                ];
            }

            return $activities;

        } catch (PDOException $e) {
            $this->logger->logError("Database error in getRecentActivity - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to retrieve recent activity', 500);
        }
    }

    /**
     * @throws Exception
     */
    private function updateUsername(string $newUsername): void
    {
        $this->pdo->beginTransaction();
        try {
            $stmt = $this->pdo->prepare("SELECT is_username_taken_by_other_user(:user_id, :username) AS exists");
            $stmt->execute(['username' => $newUsername, 'user_id' => $this->userId]);
            if ($stmt->fetchColumn() === 1) {
                $this->logger->logWarning("Username already taken - Username: $newUsername, User ID: $this->userId");
                throw new CustomException('Username is already taken', 400);
            }

            $ip_addr = $_SERVER['REMOTE_ADDR'];
            $updateStmt = $this->pdo->prepare("SELECT update_username(:user_id, :username, :ip_addr)");
            $updateStmt->execute(['username' => $newUsername, 'user_id' => $this->userId, 'ip_addr' => $ip_addr]);

            $this->pdo->commit();

            $this->session['username'] = $newUsername;
            $this->logger->logDebug("Username updated - User ID: $this->userId, New Username: $newUsername");

            $this->sendResponse([
                'success' => true,
                'message' => 'Username updated successfully',
                'new_username' => $newUsername
            ]);
        } catch (PDOException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Database error during username update - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to update username', 500);
        }
    }

    private function updateEmail(string $newEmail): void
    {
        $this->pdo->beginTransaction();
        try {
            $stmt = $this->pdo->prepare("SELECT is_email_taken_by_other_user(:user_id, :email) AS exists");
            $stmt->execute(['email' => $newEmail, 'user_id' => $this->userId]);

            if ($stmt->fetchColumn() == 1) {
                $this->logger->logWarning("Email already registered - User ID: $this->userId, Email: $newEmail");
                throw new CustomException('Email is already registered', 400);
            }

            $ip_addr = $_SERVER['REMOTE_ADDR'];
            $updateStmt = $this->pdo->prepare("
                SELECT update_email(:user_id, :email, :ip_addr)
            ");
            $updateStmt->execute([
                'email' => $newEmail,
                'user_id' => $this->userId,
                'ip_addr' => $ip_addr
            ]);

            $this->pdo->commit();

            if ($updateStmt->rowCount() === 0) {
                $this->logger->logError("Email update failed - User ID: $this->userId");
                throw new CustomException('Failed to update email', 500);
            }

            $this->logger->logDebug("Email updated successfully - User ID: $this->userId");

            $this->sendResponse([
                'success' => true,
                'message' => 'Email updated successfully. Please verify your new email.',
                'new_email' => htmlspecialchars($newEmail, ENT_QUOTES, 'UTF-8')
            ]);

        } catch (PDOException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Database error during email update - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to update email', 500);
        }
    }

    private function updateFullName(string $newFullName): void
    {
        $this->pdo->beginTransaction();
        try {
            $sanitizedFullName = htmlspecialchars($newFullName, ENT_QUOTES, 'UTF-8');
            $stmt = $this->pdo->prepare("SELECT update_full_name(:user_id, :full_name)");
            $stmt->execute([
                'user_id' => $this->userId,
                'full_name' => $sanitizedFullName
            ]);

            $this->pdo->commit();
            $this->logger->logDebug("Full name updated - User ID: $this->userId");

            $this->sendResponse([
                'success' => true,
                'message' => 'Name updated successfully',
                'new_bio' => $sanitizedFullName
            ]);
        } catch (PDOException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Database error during name update - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to update name', 500);
        }
    }

    private function updateBio(string $newBio): void
    {
        $this->pdo->beginTransaction();
        try {
            $sanitizedBio = htmlspecialchars(trim($newBio), ENT_QUOTES, 'UTF-8');

            $stmt = $this->pdo->prepare("SELECT update_bio(:user_id, :bio)");
            $stmt->execute([
                'user_id' => $this->userId,
                'bio' => $sanitizedBio
            ]);

            $this->pdo->commit();

            $this->logger->logDebug("Bio updated successfully - User ID: $this->userId");

            $this->sendResponse([
                'success' => true,
                'message' => 'Bio updated successfully',
                'new_bio' => $sanitizedBio
            ]);

        } catch (PDOException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Database error during bio update - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to update bio', 500);
        }
    }

    private function updateSocialLinks(array $socialData): void
    {
        try {
            $allowedPlatforms = ['github', 'twitter', 'website'];
            $sanitizedData = [];

            foreach ($allowedPlatforms as $platform) {
                $url = $socialData[$platform] ?? '';

                if (!empty($url)) {
                    if (!filter_var($url, FILTER_VALIDATE_URL)) {
                        $this->logger->logWarning("Invalid $platform URL - User ID: $this->userId, URL: $url");
                        throw new CustomException("Invalid $platform URL", 400);
                    }

                    if (strlen($url) > $this->generalConfig['user']['MAX_SOCIAL_URL_LENGTH']) {
                        $this->logger->logWarning("$platform URL too long - User ID: $this->userId");
                        throw new CustomException("$platform URL is too long", 400);
                    }

                    $sanitizedData[$platform] = filter_var($url, FILTER_SANITIZE_URL);
                } else {
                    $sanitizedData[$platform] = null;
                }
            }

            $this->pdo->beginTransaction();

            $stmt = $this->pdo->prepare("SELECT update_urls(:user_id, :github, :twitter, :website)");
            $stmt->execute([
                'user_id' => $this->userId,
                'github' => $sanitizedData['github'],
                'twitter' => $sanitizedData['twitter'],
                'website' => $sanitizedData['website']
            ]);

            $this->pdo->commit();

            $this->logger->logDebug("Social links updated - User ID: $this->userId");

            $this->sendResponse([
                'success' => true,
                'message' => 'Social links updated successfully',
                'social_links' => $sanitizedData
            ]);

        } catch (PDOException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Database error during social links update - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to update social links', 500);
        }
    }

    /**
     * @throws RandomException
     */
    private function handleAvatarUpload(): void
    {
        try {
            if (!isset($this->files['avatar']) || !is_uploaded_file($this->files['avatar']['tmp_name'])) {
                $this->logger->logWarning("Invalid file upload attempt - User ID: $this->userId");
                throw new CustomException('No file uploaded or upload error', 400);
            }

            $file = $this->files['avatar'];

            if ($file['error'] !== UPLOAD_ERR_OK) {
                $this->logger->logWarning("File upload error - User ID: $this->userId, Error Code: {$file['error']}");
                throw new CustomException('File upload failed', 400);
            }

            if ($file['size'] > $this->generalConfig['user']['MAX_AVATAR_SIZE']) {
                $this->logger->logWarning("Avatar file too large - User ID: $this->userId, Size: {$file['size']}");
                throw new CustomException(sprintf('Image must be less than %dMB', $this->generalConfig['user']['MAX_AVATAR_SIZE'] / 1024 / 1024), 400);
            }

            $fileInfo = finfo_open(FILEINFO_MIME_TYPE);
            $mimeType = finfo_file($fileInfo, $file['tmp_name']);
            finfo_close($fileInfo);

            if (!in_array($mimeType, $this->generalConfig['user']['ALLOWED_AVATAR_TYPES'])) {
                $this->logger->logWarning("Invalid avatar file type - User ID: $this->userId, Type: $mimeType");
                throw new CustomException(
                    sprintf('Only %s images are allowed', implode(', ', $this->generalConfig['user']['ALLOWED_AVATAR_TYPES'])),
                    400
                );
            }

            $stmt = $this->pdo->prepare("SELECT get_user_avatar(:user_id) AS avatar_url");
            $stmt->execute(['user_id' => $this->userId]);
            $oldAvatar = $stmt->fetch();
            $oldAvatarUrl = $oldAvatar['avatar_url'] ?? '';

            if ($oldAvatarUrl && str_starts_with($oldAvatarUrl, '/uploads/avatars/')) {
                $oldFilePath = $this->server['DOCUMENT_ROOT'] . $oldAvatarUrl;
                if ($this->system->file_exists($oldFilePath) && is_writable($oldFilePath)) {
                    if (!$this->system->unlink($oldFilePath)) {
                        $this->logger->logError("Failed to delete old avatar - User ID: $this->userId, Path: $oldFilePath");
                        throw new CustomException('Error processing avatar', 500);
                    }
                }
            }

            $extensionMap = [
                'image/jpeg' => 'jpg',
                'image/png' => 'png',
                'image/gif' => 'gif'
            ];
            $extension = $extensionMap[$mimeType] ?? 'jpg';
            $filename = 'avatar_' . $this->userId . '_' . bin2hex(random_bytes(8)) . '.' . $extension;
            $uploadDir = $this->server['DOCUMENT_ROOT'] . '/uploads/avatars/';
            $uploadPath = '/uploads/avatars/' . $filename;
            $fullPath = $uploadDir . $filename;

            if (!$this->system->is_dir($uploadDir) && !$this->system->mkdir($uploadDir, 0755, true)) {
                $this->logger->logError("Failed to create avatar directory - Path: $uploadDir");
                throw new CustomException('Failed to process avatar', 500);
            }

            try {
                $imagick = new Imagick($file['tmp_name']);
                $imagick->stripImage(); // removes all metadata
                $imagick->writeImage($file['tmp_name']); // overwrite the temp file without metadata
                $imagick->clear();
            } catch (Exception $e) {
                $this->logger->logError("Failed to strip image metadata - User ID: $this->userId - " . $e->getMessage());
                throw new CustomException('Error processing image', 500);
            }

            if (!$this->system->move_uploaded_file($file['tmp_name'], $fullPath)) {
                $this->logger->logError("Failed to save avatar - User ID: $this->userId, Path: $fullPath");
                throw new CustomException('Error processing request', 500);
            }

            $this->system->chmod($fullPath, 0644);

            $updateStmt = $this->pdo->prepare("SELECT update_user_avatar(:user_id, :avatar_url)");
            $updateStmt->execute([
                'avatar_url' => $uploadPath,
                'user_id' => $this->userId
            ]);

            $this->logger->logDebug("Avatar updated successfully - User ID: $this->userId");

            $this->sendResponse([
                'success' => true,
                'message' => 'Avatar updated successfully',
                'avatar_url' => $uploadPath
            ]);

        } catch (PDOException $e) {
            $this->logger->logError("Database error during avatar update - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to update avatar', 500);
        }
    }

    private function handleAvatarUpdate(): void
    {
        try {
            $input = $this->system->file_get_contents('php://input');
            if ($input === false) {
                throw new CustomException('Failed to read input data', 400);
            }

            $data = json_decode($input, true);
            if (json_last_error() !== JSON_ERROR_NONE) {
                throw new CustomException('Invalid JSON data', 400);
            }

            $avatar = $data['avatar'] ?? null;
            if ($avatar === null) {
                throw new CustomException('Avatar selection cannot be empty', 400);
            }

            $allowedAvatars = ['avatar1', 'avatar2', 'avatar3'];
            if (!in_array($avatar, $allowedAvatars, true)) {
                throw new CustomException('Invalid avatar selection', 400);
            }

            $stmt = $this->pdo->prepare("SELECT get_user_avatar(:user_id) AS avatar_url");
            $stmt->execute(['user_id' => $this->userId]);
            $oldAvatar = $stmt->fetch();
            $oldAvatarUrl = $oldAvatar['avatar_url'] ?? '';

            if ($oldAvatarUrl && str_starts_with($oldAvatarUrl, '/uploads/avatars/')) {
                $oldFilePath = $this->server['DOCUMENT_ROOT'] . $oldAvatarUrl;
                if ($this->system->file_exists($oldFilePath) && is_writable($oldFilePath)) {
                    if (!$this->system->unlink($oldFilePath)) {
                        $this->logger->logError("Failed to delete old avatar file - User ID: $this->userId, Path: $oldFilePath");
                        throw new CustomException('Could not delete old avatar file', 500);
                    }
                }
            }

            $avatarPath = '/assets/avatars/' . basename($avatar) . '.png';

            $updateStmt = $this->pdo->prepare("SELECT update_user_avatar(:user_id, :avatar_url)");
            $updateStmt->execute([
                'avatar_url' => $avatarPath,
                'user_id' => $this->userId
            ]);

            $this->logger->logDebug("Avatar updated via selection - User ID: $this->userId, Avatar: $avatar");

            $this->sendResponse([
                'success' => true,
                'message' => 'Avatar updated successfully',
                'avatar_url' => $avatarPath
            ]);

        } catch (PDOException $e) {
            $this->logger->logError("Database error during avatar update - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to update avatar', 500);
        }
    }

    private function changePassword(string $currentPassword, string $newPassword): void
    {
        $this->pdo->beginTransaction();
        try {
            if (empty($currentPassword) || empty($newPassword)) {
                throw new CustomException('Both current and new password are required', 400);
            }

            if (strlen($newPassword) < $this->generalConfig['user']['MIN_PASSWORD_LENGTH']) {
                throw new CustomException('New password must be at least 8 characters', 400);
            }

            if (strlen($newPassword) > $this->generalConfig['user']['MAX_PASSWORD_LENGTH']) {
                throw new CustomException('Password is too long', 400);
            }

            $stmt = $this->pdo->prepare("SELECT get_user_password_salt(:username) AS salt");
            $stmt->execute(['username' => $this->session['username']]);
            $passwordSalt = $stmt->fetch(PDO::FETCH_ASSOC)['salt'];

            if (!$passwordSalt) {
                $this->logger->logError("User not found during password change - User ID: $this->userId");
                throw new CustomException('User not found', 404);
            }

            $oldPasswordHash = hash('sha512', $passwordSalt . $currentPassword);
            $userStmt = $this->pdo->prepare("SELECT authenticate_user(:username, :password_hash) AS user_id");
            $userStmt->execute([
                'username' => $this->session['username'],
                'password_hash' => $oldPasswordHash
            ]);
            $user_id = $userStmt->fetch(PDO::FETCH_ASSOC)['user_id'];


            if (!$user_id) {
                $this->logger->logWarning("Incorrect current password attempt - User ID: $this->userId");
                throw new CustomException('Current password is incorrect', 400);
            }

            if (hash('sha512', $passwordSalt . $newPassword) === $oldPasswordHash) {
                throw new CustomException('New password must be different from current password', 400);
            }

            $newSalt = bin2hex(random_bytes(16));
            $newPasswordHash = hash('sha512', $newSalt . $newPassword);
            if (!$newPasswordHash) {
                throw new CustomException('Error hashing password', 500);
            }

            $updateStmt = $this->pdo->prepare("SELECT change_user_password(:user_id, :old_password_hash, :new_password_hash, :new_password_salt)");
            $updateStmt->execute([
                'user_id' => $this->userId,
                'old_password_hash' => $oldPasswordHash,
                'new_password_hash' => $newPasswordHash,
                'new_password_salt' => $newSalt
            ]);

            $this->pdo->commit();

            $this->logger->logDebug("Password changed successfully - User ID: $this->userId");

            $this->sendResponse([
                'success' => true,
                'message' => 'Password changed successfully'
            ]);

        } catch (PDOException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Database error during password change - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to change password', 400);
        }
    }

    private function getCategoryData(): array
    {
        try {
            $stmt = $this->pdo->query("SELECT get_all_challenge_categories() AS category");
            $allCategories = $stmt->fetchAll(PDO::FETCH_COLUMN);

            if (empty($allCategories)) {
                throw new CustomException('No challenge categories found', 500);
            }

            $totals = [];
            $stmt = $this->pdo->query("
                SELECT category, total FROM get_challenge_count_by_categories()
            ");
            while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
                $totals[$row['category']] = (int)$row['total'];
            }

            $stmt = $this->pdo->prepare("
                SELECT 
                    category,
                    solved
                FROM get_user_solved_challenge_count_by_categories(:user_id)
            ");
            $stmt->execute(['user_id' => $this->userId]);
            $solved = $stmt->fetchAll(PDO::FETCH_KEY_PAIR);

            $percentages = [];
            foreach ($allCategories as $category) {
                $total = $totals[$category] ?? 0;
                $solvedCount = $solved[$category] ?? 0;
                $percentages[$category] = $total > 0 ? round(($solvedCount / $total) * 100) : 0;
            }

            return [
                'categories' => $allCategories,
                'percentages' => array_values($percentages),
                'solved_counts' => array_replace(array_fill_keys($allCategories, 0), $solved)
            ];

        } catch (PDOException $e) {
            $this->logger->logError("Database error in getCategoryData - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to retrieve category data', 500);
        }
    }

    private function handleVpnConfigDownload(): void
    {
        try {
            $username = $this->session['username'] ?? 'user_' . $this->userId;

            $safeUsername = preg_replace('/[^a-zA-Z0-9_]/', '', $username);
            $safeUsername = $safeUsername == '' ? 'user_' . $this->userId : $safeUsername;
            $filename = $safeUsername . '.ovpn';

            while (ob_get_level()) {
                ob_end_clean();
            }

            header('Content-Description: File Transfer');
            header('Content-Type: application/octet-stream');
            header('Content-Disposition: attachment; filename="' . $filename . '"');
            header('Expires: 0');
            header('Cache-Control: must-revalidate, post-check=0, pre-check=0');
            header('Pragma: public');
            header('X-Content-Type-Options: nosniff');
            header('X-Frame-Options: DENY');

            $data = $this->curlHelper->makeBackendRequest(
                '/get-user-config',
                'POST',
                $this->authHelper->getBackendHeaders(),
                ['user_id' => $this->userId],
            );

            if (!$data['success'] || $data['http_code'] !== 200 || empty($data['response'])) {
                $this->logger->logError("Failed to retrieve VPN config - User ID: $this->userId, Response: " . json_encode($data));
                throw new CustomException('Failed to retrieve VPN configuration', 500);
            }

            echo $data['response'];

            defined('PHPUNIT_RUNNING') || exit;

        } catch (PDOException $e) {
            $this->logger->logError("Database error during VPN config download - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to process VPN configuration', 500);
        }
    }

    /**
     * @throws Exception
     */
    private function handleDeleteRequest(): void
    {
        try {
            $input = json_decode($this->system->file_get_contents('php://input'), true);
            if (json_last_error() !== JSON_ERROR_NONE) {
                $this->logger->logWarning("Invalid JSON in delete request - User ID: $this->userId");
                throw new CustomException('Invalid request data', 400);
            }

            $password = $input['password'] ?? '';
            $hashedPassword = $this->verifyUserPassword($password);
            $this->stopRunningChallenge();
            $this->deleteUserConfigurations();
            $this->deleteUserOvaFiles($hashedPassword);
            $this->deleteAllUserData($hashedPassword);
            $this->destroyUserSession();

            $this->logger->logInfo("Account deleted successfully - User ID: $this->userId");
            $this->sendSuccessResponse();

        } catch (CustomException $e) {
            $this->logger->logError("Account deletion failed - User ID: $this->userId - " . $e->getMessage());
            throw $e;
        } catch (Exception $e) {
            $this->logger->logError("Unexpected error during account deletion - User ID: $this->userId - " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        }
    }

    private function verifyUserPassword(string $password): string
    {
        try {
            if (empty($password)) {
                throw new CustomException('Password cannot be empty', 400);
            }

            $stmt = $this->pdo->prepare("SELECT get_user_password_salt(:username) AS salt");
            $stmt->execute(['username' => $this->session['username']]);
            $passwordSalt = $stmt->fetchColumn();

            if (!$passwordSalt) {
                $this->logger->logWarning("Incorrect password during verification - User ID: $this->userId");
                throw new CustomException('Incorrect password', 400);
            }

            $hashedPassword = hash('sha512', $passwordSalt . $password);
            $stmt = $this->pdo->prepare("SELECT authenticate_user(:username, :password_hash) AS user_id");
            $stmt->execute([
                'username' => $this->session['username'],
                'password_hash' => $hashedPassword
            ]);
            $user = $stmt->fetch(PDO::FETCH_ASSOC);

            if(!$user || !$user['user_id']) {
                $this->logger->logWarning("Incorrect password during verification - User ID: $this->userId");
                throw new CustomException('Incorrect password', 400);
            }

            return $hashedPassword;

        } catch (PDOException $e) {
            $this->logger->logError("Database error during password verification - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to verify password', 500);
        }
    }

    private function stopRunningChallenge(): void
    {
        try {
            $stmt = $this->pdo->prepare("SELECT get_user_running_challenge(:user_id) AS running_challenge");
            $stmt->execute(['user_id' => $this->userId]);
            $result = $stmt->fetch(PDO::FETCH_ASSOC);

            if ($result && $result['running_challenge'] !== null) {
                $stmt = $this->pdo->prepare("SELECT get_challenge_template_id_from_running_challenge(:user_id) AS template_id");
                $stmt->execute(['user_id' => $this->userId]);
                $templateResult = $stmt->fetch(PDO::FETCH_ASSOC);
                $this->logUserNetworkTraceStop($templateResult['template_id']);
                $response = $this->curlHelper->makeBackendRequest(
                    '/stop-challenge',
                    'POST',
                    $this->authHelper->getBackendHeaders(),
                    ['user_id' => $this->userId]
                );

                if (!$response['success'] || $response['http_code'] !== 200) {
                    $this->logger->logError("Failed to stop running challenge - User ID: $this->userId, Response: " . json_encode($response));
                    throw new CustomException("Failed to stop current challenge", 500);
                }
                $this->logger->logDebug("Stopped running challenge - User ID: $this->userId");
            }

        } catch (PDOException $e) {
            $this->logger->logError("Database error during challenge stop - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to stop running challenge', 500);
        }
    }

    private function logUserNetworkTraceStop($challengeId): void
    {
        try {
            $stmt = $this->pdo->prepare("
                SELECT stop_user_network_trace(:userid, :challenge_template_id)
            ");
            $stmt->execute([
                'userid' => $this->userId,
                'challenge_template_id' => $challengeId
            ]);
            $this->logger->logDebug("UserNetworkTrace Entry Created - User ID: $this->userId");
        } catch (PDOException $e) {
            $this->logger->logError("Failed to create user network trace - User ID: $this->userId, Error: " . $e->getMessage());
            throw new CustomException("Failed to stop challenge attempt", 500);
        }
    }

    private function deleteUserConfigurations(): void
    {
        try {
            $response = $this->curlHelper->makeBackendRequest(
                '/delete-user-config',
                'POST',
                $this->authHelper->getBackendHeaders(),
                ['user_id' => $this->userId]
            );

            if (!$response['success'] || $response['http_code'] !== 200) {
                $this->logger->logError("Failed to delete user config - User ID: $this->userId, Response: " . json_encode($response));
                throw new CustomException("Failed to process request", 500);
            }
        } catch (CustomException $e) {
            $this->logger->logError("Error deleting user configurations - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to process request', 500);
        } catch (Exception $e) {
            $this->logger->logError("Unexpected error deleting user configurations - User ID: $this->userId - " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        }
    }

    private function deleteUserOvaFiles(string $hashedPassword): void
    {
        try {
            $stmt = $this->pdo->prepare("
                SELECT ova_id, proxmox_filename FROM get_user_disk_files_display_data(:user_id)
            ");
            $stmt->execute(['user_id' => $this->userId]);
            $ovas = $stmt->fetchAll(PDO::FETCH_ASSOC);

            foreach ($ovas as $ova) {
                try {
                    $endpoint = "/api2/json/nodes/" . $this->env['PROXMOX_HOSTNAME'] . "/storage/local/content/import/" .
                        urlencode($ova['proxmox_filename']);
                    $result = $this->curlHelper->makeCurlRequest($endpoint, 'DELETE', $this->authHelper->getAuthHeaders());

                    if (!$result || $result['http_code'] !== 200) {
                        throw new CustomException('Failed to delete virtual machine', 500);
                    }

                    $this->pdo->prepare("SELECT delete_user_disk_files(:user_id, :ova_id, :password_hash)")
                        ->execute([
                            'user_id' => $this->userId,
                            'ova_id' => $ova['ova_id'],
                            'password_hash' => $hashedPassword
                        ]);
                } catch (CustomException $e) {
                    $this->logger->logError("Failed to delete OVA - User ID: $this->userId, OVA ID: {$ova['ova_id']} - " . $e->getMessage());
                } catch (Exception $e) {
                    $this->logger->logError("Unexpected error deleting OVA - User ID: $this->userId, OVA ID: {$ova['ova_id']} - " . $e->getMessage());
                }
            }

        } catch (PDOException $e) {
            $this->logger->logError("Database error during OVA deletion - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to delete OVA files', 500);
        }
    }

    private function deleteAllUserData(string $hashedPassword): void
    {
        try {
            $this->pdo->beginTransaction();

            $ip_addr = $_SERVER['REMOTE_ADDR'];
            $this->pdo->prepare("SELECT delete_user_data(:user_id, :password_hash, :ip_addr)")
                ->execute([
                    'user_id' => $this->userId,
                    'password_hash' => $hashedPassword,
                    'ip_addr' => $ip_addr
                ]);

            $this->pdo->commit();
        } catch (CustomException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Failed to delete all user data - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to delete account data', 500);
        } catch (PDOException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Database error during user data deletion - User ID: $this->userId - " . $e->getMessage());
            throw new CustomException('Failed to delete account data', 500);
        } catch (Exception $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Unexpected error during user data deletion - User ID: $this->userId - " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        }
    }

    private function destroyUserSession(): void
    {
        try {
            $this->session->regenerate_id(true);
            $this->session->clear();

            if ($this->session->status() === PHP_SESSION_ACTIVE) {
                $this->session->destroy();
            }

            $params = $this->session->get_cookie_params();
            $this->system->setcookie(
                $this->session->name(),
                '',
                [
                    'expires' => $this->system->time() - 3600,
                    'path' => $params['path'],
                    'domain' => $params['domain'],
                    'secure' => $params['secure'],
                    'httponly' => $params['httponly'],
                    'samesite' => $params['samesite']
                ]
            );

            $this->system->setcookie(
                'csrf_token',
                '',
                [
                    'expires' => $this->system->time() - 3600,
                    'path' => '/',
                    'domain' => '',
                    'secure' => true,
                    'httponly' => true,
                    'samesite' => 'Strict'
                ]
            );

        } catch (CustomException $e) {
            $this->logger->logError("Error destroying session - " . $e->getMessage());
            throw new CustomException('Failed to destroy session', 500);
        } catch (Exception $e) {
            $this->logger->logError("Unexpected error destroying session - " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        }
    }

    private function sendSuccessResponse(): void
    {
        $this->sendResponse([
            'success' => true,
            'message' => 'Account deleted successfully',
            'redirect' => '/'
        ]);
    }

    private function sendResponse(array $response): void
    {
        echo json_encode($response);
    }

    private function handleError(Exception $e): void
    {
        $errorCode = $e->getCode() ?: 500;
        $errorMessage = $e->getMessage();

        if ($errorCode === 401) {
            $this->session->unset();
            $this->session->destroy();
            $this->logger->logWarning("Session destroyed due to unauthorized access");
        }

        if ($errorCode >= 500) {
            $errorMessage = 'An internal server error occurred';
            $this->logger->logError("Internal error : " . $e->getMessage());
        } else {
            $this->logger->logError("Profile error: " . $e->getMessage());
        }

        http_response_code($errorCode);
        $this->sendResponse([
            'success' => false,
            'message' => $errorMessage,
            'redirect' => $errorCode === 401 ? '/login' : null
        ]);
    }
}

// @codeCoverageIgnoreStart

if(defined('PHPUNIT_RUNNING'))
    return;

try {
    header('Content-Type: application/json');
    $config = require __DIR__ . '/../config/backend.config.php';
    $system = new SystemWrapper();
    $generalConfig = json_decode($system->file_get_contents(__DIR__ . '/../config/general.config.json'), true);

    $handler = new ProfileHandler(generalConfig: $generalConfig);
    $handler->handleRequest();
} catch (CustomException $e) {
    $errorCode = $e->getCode() ?: 500;
    http_response_code($errorCode);
    $logger = new Logger("/profile");
    $logger->logError("Error in profile endpoint: " . $e->getMessage() . " (Code: $errorCode)");
    $response = [
        'success' => false,
        'message' => $e->getMessage()
    ];

    if ($errorCode === 401) {
        $response['redirect'] = '/login';
    }

    echo json_encode($response);
} catch (Exception $e) {
    http_response_code(500);
    $logger = new Logger("/profile");
    $logger->logError("Unexpected error in profile endpoint: " . $e->getMessage());
    echo json_encode([
        'success' => false,
        'message' => 'An unexpected error occurred'
    ]);
}

// @codeCoverageIgnoreEnd