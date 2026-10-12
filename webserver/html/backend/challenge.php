<?php
declare(strict_types=1);

require_once __DIR__ . '/../vendor/autoload.php';

class ChallengeHandler
{
    private PDO $pdo;
    private ?int $userId;
    private array $config;
    private string $route;

    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ICurlHelper $curlHelper;
    private IAuthHelper $authHelper;
    private IChallengeHelper $challengeHelper;
    private ILogger $logger;

    private ISession $session;
    private IServer $server;
    private IGet $get;
    private ICookie $cookie;
    
    private ISystem $system;

    /**
     * @throws Exception
     */
    public function __construct(
        array $config,
        
        IDatabaseHelper $databaseHelper = null,
        ISecurityHelper $securityHelper = null,
        ICurlHelper $curlHelper = null,
        IAuthHelper $authHelper = null,
        IChallengeHelper $challengeHelper = null,
        ILogger $logger = null,
        
        ISession $session = new Session(),
        IServer $server = new Server(),
        IGet $get = new Get(),
        
        ISystem $system = new SystemWrapper(),
        IEnv $env = new Env(),
        ICookie $cookie = new Cookie()
    )
    {
        $this->session = $session;
        $this->server = $server;
        $this->get = $get;
        $this->cookie = $cookie;
        $this->route = "/challenge";

        $this->databaseHelper = $databaseHelper ?? new DatabaseHelper($logger, $system);
        $this->securityHelper = $securityHelper ?? new SecurityHelper($logger, $session, $system);
        $this->curlHelper = $curlHelper ?? new CurlHelper($env);
        $this->authHelper = $authHelper ?? new AuthHelper($logger, $system, $env);
        $this->challengeHelper = $challengeHelper ?? new ChallengeHelper();
        $this->logger = $logger ?? new Logger(route: $this->route, system: $system);
        
        $this->system = $system;

        $this->config = $config;
        $this->initSession();
        $this->validateCSRF();
        $this->pdo = $this->databaseHelper->getPDO();
        $this->userId = $this->session['user_id'];
        $this->logger->logDebug("Initialized ChallengeHandler for user ID: $this->userId");
    }

    /**
     * @throws Exception
     */
    private function initSession(): void
    {
        $this->securityHelper->initSecureSession();

        if (!$this->securityHelper->validateSession()) {
            $this->logger->logWarning("Unauthorized access attempt to challenge route - IP: " . $this->logger->anonymizeIp($this->server['REMOTE_ADDR'] ?? 'unknown'));
            throw new CustomException('Unauthorized - Please login', 401);
        }
    }

    /**
     * @throws Exception
     */
    private function validateCSRF(): void
    {
        $csrfToken = $this->cookie['csrf_token'] ?? '';
        if (!$this->securityHelper->validateCsrfToken($csrfToken)) {
            $this->logger->logWarning("Invalid CSRF token in challenge route - User ID: " . ($this->session['user_id'] ?? 'unknown'));
            throw new CustomException('Invalid CSRF token', 403);
        }
    }

    public function handleRequest(): void
    {
        try {
            $method = $this->server['REQUEST_METHOD'];

            switch ($method) {
                case 'POST':
                    $this->handlePostRequest();
                    break;
                case 'GET':
                    $this->handleGetRequest();
                    break;
                default:
                    $this->logger->logWarning("Invalid request method in challenge route - Method: $method");
                    throw new CustomException('Method not allowed', 405);
            }
        } catch (CustomException $e) {
            $this->handleError($e);
        } catch (Exception $e) {
            $this->logger->logError("Unexpected error in challenge route: " . $e->getMessage());
            $this->handleError(new Exception('Internal Server Error', 500));
        }
    }

    /**
     * @throws Exception
     */
    private function handlePostRequest(): void
    {
        $input = $this->getJsonInput();
        $this->validatePostInput($input);

        $challengeId = $this->validateChallengeId($input['challenge_id']);
        $action = $input['action'];

        switch ($action) {
            case 'deploy':
                $this->handleDeploy($challengeId);
                break;
            case 'cancel':
                $this->handleCancel($challengeId);
                break;
            case 'submit_flag':
                $this->handleFlagSubmission($challengeId, $input);
                break;
            case 'extend_time':
                $this->handleTimeExtension($challengeId);
                break;
        }
    }

    /**
     * @throws Exception
     */
    private function getJsonInput()
    {
        $input = json_decode($this->system->file_get_contents('php://input'), true);
        if (json_last_error() !== JSON_ERROR_NONE) {
            $this->logger->logWarning("Invalid JSON input in challenge route - User ID: $this->userId");
            throw new CustomException('Invalid JSON input', 400);
        }
        return $input;
    }

    /**
     * @throws Exception
     */
    private function validatePostInput(array $input): void
    {
        $requiredFields = ['action', 'challenge_id'];
        foreach ($requiredFields as $field) {
            if (!isset($input[$field])) {
                $this->logger->logWarning("Missing required field in challenge route - Field: $field, User ID: $this->userId");
                throw new CustomException("Missing required parameter: $field", 400);
            }
        }

        if (!in_array($input['action'], $this->config['challenge']['ALLOWED_ACTIONS'])) {
            $this->logger->logWarning("Invalid action in challenge route - Action: {$input['action']}, User ID: $this->userId");
            throw new CustomException('Invalid action', 400);
        }
    }

    /**
     * @throws Exception
     */
    private function validateChallengeId($challengeId)
    {
        $id = filter_var($challengeId, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]);
        if ($id === false) {
            $this->logger->logWarning("Invalid challenge ID - ID: $challengeId, User ID: $this->userId");
            throw new CustomException('Invalid challenge ID', 400);
        }
        return $id;
    }

    /**
     * @throws Exception
     */
    private function handleDeploy(int $challengeId): void
    {
        $this->checkRunningChallenge();
        $this->validateChallengeStatus($challengeId);

        $lockFile = $this->acquireDeploymentLock($this->userId);
        if ($lockFile === false) {
            throw new CustomException("A deployment is already in progress. Please wait.", 409);
        }

        try {
            $result = $this->curlHelper->makeBackendRequest(
                '/launch-challenge',
                'POST',
                $this->authHelper->getBackendHeaders(),
                [
                    'user_id' => $this->userId,
                    'challenge_template_id' => $challengeId
                ]
            );

            if (!$result['success'] || $result['http_code'] !== 200) {
                $errorMsg = $result['error'] ?? "HTTP {$result['http_code']}";
                $this->logger->logError("Failed to launch challenge - Error: $errorMsg, User ID: $this->userId");
                throw new CustomException("Failed to launch challenge", 500);
            }

            $responseData = json_decode($result['response'], true);
            $entrypoints = $responseData['entrypoints'] ?? [];

            $this->startNewAttempt($challengeId);
            $this->logUserNetworkTraceStart($challengeId);

            $this->logger->logDebug("Challenge deployed successfully - ID: $challengeId, User ID: $this->userId");

            $this->sendResponse([
                'success' => true,
                'message' => 'Challenge deployment initiated',
                'entrypoints' => $entrypoints,
                'elapsed_seconds' => $this->challengeHelper->getElapsedSecondsForChallenge($this->pdo,$this->userId,$challengeId),
                'remaining_seconds' => $this->getRemainingSecondsForChallenge($challengeId),
                'remaining_extensions' => $this->getRemainingExtensionsForChallenge($challengeId)
            ]);
        } finally {
            $this->releaseDeploymentLock($lockFile);
        }
    }

    private function acquireDeploymentLock(int $userId)
    {
        $lockDir = '/var/www/deployment_locks';

        if (!is_dir($lockDir)) {
            mkdir($lockDir, 0755, true);
        }

        $lockPath = $lockDir . "/user_{$userId}.lock";

        $fp = fopen($lockPath, 'c');

        if ($fp === false) {
            $this->logger->logError("Failed to create lock file for user {$userId}");
            return false;
        }

        if (!flock($fp, LOCK_EX | LOCK_NB)) {
            fclose($fp);
            $this->logger->logDebug("Lock already held for user {$userId}");
            return false;
        }

        ftruncate($fp, 0);
        fwrite($fp, "PID: " . getmypid() . "\nTime: " . date('Y-m-d H:i:s') . "\n");
        fflush($fp);

        return $fp;
    }

    private function releaseDeploymentLock($lockFile): void
    {
        if ($lockFile !== false && is_resource($lockFile)) {
            flock($lockFile, LOCK_UN);
            fclose($lockFile);
        }
    }

    /**
     * @throws Exception
     */
    private function checkRunningChallenge(): void
    {
        $stmt = $this->pdo->prepare("
            SELECT get_user_running_challenge(:user_id) AS running_challenge
        ");
        $stmt->execute(['user_id' => $this->userId]);
        $user = $stmt->fetch();

        if ($user['running_challenge']) {
            $this->logger->logWarning("User already has a running challenge - User ID: $this->userId");
            throw new CustomException("You already have a running challenge", 400);
        }
    }

    /**
     * @throws Exception
     */
    private function validateChallengeStatus(int $challengeId): void
    {
        $stmt = $this->pdo->prepare("
            SELECT marked_for_deletion, is_active 
            FROM get_deployable_conditions(:template_id)
        ");
        $stmt->execute(['template_id' => $challengeId]);
        $template = $stmt->fetch();

        if (!$template) {
            $this->logger->logWarning("Challenge not found - ID: $challengeId, User ID: $this->userId");
            throw new CustomException("Challenge not found", 404);
        }

        if ($template['marked_for_deletion']) {
            $this->logger->logWarning("Attempt to deploy challenge marked for deletion - ID: $challengeId, User ID: $this->userId");
            throw new CustomException("This challenge has been marked for deletion and cannot be deployed", 400);
        }

        if (!$template['is_active'] && !$this->isCreator($challengeId)) {
            $this->logger->logWarning("Attempt to deploy inactive challenge - ID: $challengeId, User ID: $this->userId");
            throw new CustomException("This challenge is currently inactive and cannot be deployed", 400);
        }
    }

    /**
     * @throws Exception
     */
    private function isCreator(int $challengeId): bool
    {
        try{
            $stmt = $this->pdo->prepare("
                SELECT get_creator_id_by_challenge_template(:challenge_id) AS creator_id
            ");
            $stmt->execute(['challenge_id' => $challengeId]);
            $creatorId = $stmt->fetchColumn();
            if($creatorId === $this->userId){
                return true;
            }
            return false;
        }catch (PDOException $e){
            $this->logger->logError("Failed to check Creator - Challenge ID: $challengeId, Error: {$e->getMessage()}");
            throw new CustomException("Failed to start Challenge", 500);
        }
    }

    /**
     * @throws Exception
     */
    private function startNewAttempt(int $challengeId): void
    {
        try {
            $stmt = $this->pdo->prepare("
                SELECT create_new_challenge_attempt(:user_id, :challenge_template_id)
            ");
            $stmt->execute([
                'user_id' => $this->userId,
                'challenge_template_id' => $challengeId
            ]);
            $this->logger->logDebug("New attempt started - Challenge ID: $challengeId, User ID: $this->userId");
        } catch (PDOException $e) {
            $this->logger->logError("Failed to start new attempt - Challenge ID: $challengeId, Error: " . $e->getMessage());
            throw new CustomException("Failed to start challenge attempt", 500);
        }
    }

    /**
     * @throws Exception
     */
    private function logUserNetworkTraceStart($challengeId): void
    {
        try {
            $stmt = $this->pdo->prepare("
                SELECT start_user_network_trace(:userid, :challenge_template_id)
            ");
            $stmt->execute([
                'userid' => $this->userId,
                'challenge_template_id' => $challengeId
            ]);
            $this->logger->logDebug("UserNetworkTrace Entry Created - User ID: $this->userId");
        } catch (PDOException $e) {
            $this->logger->logError("Failed to create user network trace - User ID: $this->userId, Error: " . $e->getMessage());
            throw new CustomException("Failed to start challenge attempt", 500);
        }
    }

    /**
     * @throws Exception
     */
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

    /**
     * @throws Exception
     */
    private function handleCancel(int $challengeId): void
    {
        $this->markAttemptAsCompleted($challengeId);
        $this->logUserNetworkTraceStop($challengeId);
        $this->stopRunningChallenge();

        if ($this->shouldDeleteChallengeTemplate($challengeId)) {
            $this->deleteChallengeTemplate($challengeId);
        }

        $this->sendResponse([
            'success' => true,
            'message' => 'Challenge cancelled successfully'
        ]);
    }

    /**
     * @throws Exception
     */
    private function stopRunningChallenge(): void
    {
        $result = $this->curlHelper->makeBackendRequest(
            '/stop-challenge',
            'POST',
            $this->authHelper->getBackendHeaders(),
            ['user_id' => $this->userId]
        );

        if (!$result['success'] || $result['http_code'] !== 200) {
            $errorMsg = $result['error'] ?? "HTTP {$result['http_code']}";
            $this->logger->logError("Failed to stop challenge - Error: $errorMsg, User ID: $this->userId");
            throw new CustomException("Failed to stop challenge", 500);
        }
    }

    /**
     * @throws Exception
     */
    private function markAttemptAsCompleted(int $challengeId): void
    {
        try {
            $stmt = $this->pdo->prepare("
                SELECT mark_attempt_completed(:user_id, :challenge_id)
            ");
            $stmt->execute([
                'user_id' => $this->userId,
                'challenge_id' => $challengeId
            ]);
            $this->logger->logDebug("Marked attempt as completed - Challenge ID: $challengeId, User ID: $this->userId");
        } catch (PDOException $e) {
            $this->logger->logError("Failed to mark attempt as completed - Challenge ID: $challengeId, Error: " . $e->getMessage());
            throw new CustomException("Failed to complete challenge attempt", 500);
        }
    }

    private function shouldDeleteChallengeTemplate(int $challengeId): bool
    {
        try {
            $stmt = $this->pdo->prepare("
                SELECT challenge_template_should_be_deleted(:template_id) AS should_delete
            ");
            $stmt->execute(['template_id' => $challengeId]);
            $shouldDelete = $stmt->fetchColumn();

            return $shouldDelete == 1;
        } catch (PDOException $e) {
            $this->logger->logError("Failed to check template deletion status - Challenge ID: $challengeId, Error: " . $e->getMessage());
            return false;
        }
    }

    /**
     * @throws Exception
     */
    private function deleteChallengeTemplate(int $challengeId): void
    {
        $this->pdo->beginTransaction();

        try {
            $result = $this->curlHelper->makeBackendRequest(
                '/delete-machine-templates',
                'POST',
                $this->authHelper->getBackendHeaders(),
                ['challenge_id' => $challengeId]
            );

            if (!$result['success'] || $result['http_code'] !== 200) {
                throw new CustomException("Failed to delete VM templates");
            }

            $stmt = $this->pdo->prepare("
                SELECT delete_challenge_template(:challenge_id)
            ");
            $stmt->execute(['challenge_id' => $challengeId]);

            $this->pdo->commit();
        } catch (CustomException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Failed to delete challenge template - ID: $challengeId, Error: " . $e->getMessage());
            throw new CustomException("Failed to delete challenge template", 500);
        } catch (Exception $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Unexpected error during challenge template deletion - ID: $challengeId, Error: " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        }
    }

    /**
     * @throws Exception
     */
    private function handleFlagSubmission(int $challengeId, array $input): void
    {
        if (!isset($input['flag'])) {
            $this->logger->logWarning("Flag submission attempt without flag - User ID: $this->userId");
            throw new CustomException("Flag missing", 400);
        }

        $flag = trim($input['flag']);
        if (empty($flag)) {
            $this->logger->logWarning("Empty flag submission attempt - User ID: $this->userId");
            throw new CustomException("Flag cannot be empty", 400);
        }

        $this->pdo->beginTransaction();

        try {
            $flagData = $this->validateAndLockFlag($challengeId, $flag);
            $this->checkDuplicateSubmission($challengeId, $flagData['id']);

            $submittedFlagsCount = $this->countSubmittedFlags($challengeId);
            $totalFlagsCount = $this->countTotalFlags($challengeId);
            $isLastFlag = ($submittedFlagsCount + 1) >= $totalFlagsCount;

            $this->recordFlagSubmission($challengeId, $flagData['id'], $isLastFlag);
            $this->pdo->commit();

            $newBadges = [];
            if ($isLastFlag) {
                $newBadges = $this->checkBadgeUnlocks($challengeId);
                $this->logger->logDebug("User completed all flags - Challenge ID: $challengeId, User ID: $this->userId");
            }

            $this->logger->logDebug("Flag accepted - Challenge ID: $challengeId, Points: {$flagData['points']}, User ID: $this->userId");

            $this->sendResponse([
                'success' => true,
                'message' => 'Flag accepted! You earned ' . $flagData['points'] . ' points!',
                'badges' => $newBadges,
                'is_complete' => $isLastFlag
            ]);
        } catch (CustomException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Flag submission failed - Challenge ID: $challengeId, Error: " . $e->getMessage());
            throw $e;
        } catch (Exception $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Unexpected error during flag submission - Challenge ID: $challengeId, Error: " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        }
    }

    /**
     * @throws Exception
     */
    private function validateAndLockFlag(int $challengeId, string $flag)
    {
        $stmt = $this->pdo->prepare("
            SELECT id, points
            FROM validate_and_lock_flag(:challenge_id, :flag, :user_id)
        ");
        $stmt->execute([
            'challenge_id' => $challengeId,
            'flag' => $flag,
            'user_id' => $this->userId
        ]);
        $flagData = $stmt->fetch();

        if (!$flagData) {
            $this->logger->logWarning("Invalid flag submitted - Challenge ID: $challengeId, User ID: $this->userId");
            throw new CustomException("Invalid flag", 400);
        }

        return $flagData;
    }

    /**
     * @throws Exception
     */
    private function checkDuplicateSubmission(int $challengeId, int $flagId): void
    {
        $stmt = $this->pdo->prepare("
            SELECT is_duplicate_flag_submission(:user_id, :challenge_id, :flag_id) AS is_duplicate
        ");
        $stmt->execute([
            'user_id' => $this->userId,
            'challenge_id' => $challengeId,
            'flag_id' => $flagId
        ]);

        if ($stmt->fetchColumn() == 1) {
            $this->logger->logWarning("Duplicate flag submission - Flag ID: $flagId, User ID: $this->userId");
            throw new CustomException("You already submitted this flag", 400);
        }
    }

    private function countSubmittedFlags(int $challengeId): int
    {
        $stmt = $this->pdo->prepare("
            SELECT get_user_submitted_flags_count_for_challenge(:user_id, :challenge_id) AS submitted_count
        ");
        $stmt->execute([
            'user_id' => $this->userId,
            'challenge_id' => $challengeId
        ]);
        return (int)$stmt->fetchColumn();
    }

    private function countTotalFlags(int $challengeId)
    {
        $stmt = $this->pdo->prepare("
            SELECT get_total_flags_count_for_challenge(:challenge_id) AS total_count
        ");
        $stmt->execute(['challenge_id' => $challengeId]);
        return $stmt->fetchColumn();
    }

    private function recordFlagSubmission(int $challengeId, int $flagId, bool $isLastFlag): void
    {
        $activeAttempt = $this->getActiveAttempt($challengeId);

        if ($activeAttempt) {
            if ($isLastFlag) {
                $this->updateRunningAttempt($activeAttempt['id'], $flagId);
            } else {
                $this->createNewCompletedAttempt($challengeId, $flagId);
            }
        } else {
            $this->handleNoActiveAttempt($challengeId, $flagId);
        }
    }

    private function getActiveAttempt(int $challengeId)
    {
        $stmt = $this->pdo->prepare("
            SELECT get_active_attempt_id(:user_id, :challenge_id) AS id
        ");
        $stmt->execute([
            'user_id' => $this->userId,
            'challenge_id' => $challengeId
        ]);
        return $stmt->fetch();
    }

    private function updateRunningAttempt(int $attemptId, int $flagId): void
    {
        $stmt = $this->pdo->prepare("
            SELECT update_running_attempt(:flag_id, :attempt_id)
        ");
        $stmt->execute([
            'flag_id' => $flagId,
            'attempt_id' => $attemptId
        ]);
    }

    private function createNewCompletedAttempt(int $challengeId, int $flagId): void
    {
        $stmt = $this->pdo->prepare("
            SELECT create_new_completed_attempt(:user_id, :challenge_template_id, :flag_id)
        ");
        $stmt->execute([
            'user_id' => $this->userId,
            'challenge_template_id' => $challengeId,
            'flag_id' => $flagId
        ]);
    }

    private function handleNoActiveAttempt(int $challengeId, int $flagId): void
    {
        $recentAttempt = $this->getRecentUnflaggedAttempt($challengeId);

        if ($recentAttempt) {
            $this->updateRecentAttempt($recentAttempt['id'], $flagId);
        } else {
            $this->createNewCompletedAttempt($challengeId, $flagId);
        }
    }

    private function getRecentUnflaggedAttempt(int $challengeId)
    {
        $stmt = $this->pdo->prepare("
            SELECT get_recent_unflagged_attempt(:user_id, :challenge_id) AS id
        ");
        $stmt->execute([
            'user_id' => $this->userId,
            'challenge_id' => $challengeId
        ]);
        return $stmt->fetch();
    }

    private function updateRecentAttempt(int $attemptId, int $flagId): void
    {
        $stmt = $this->pdo->prepare("
            SELECT update_recent_attempt(:flag_id, :attempt_id)
        ");
        $stmt->execute([
            'flag_id' => $flagId,
            'attempt_id' => $attemptId
        ]);
    }

    /**
     * @throws Exception
     */
    private function handleGetRequest(): void
    {
        $challengeId = $this->validateChallengeId($this->get['id'] ?? 0);

        try {
            $challenge = $this->getChallengeDetails($challengeId);
            $challengeStatus = $this->getChallengeStatus($challengeId);
            $isSolved = $this->challengeHelper->isChallengeSolved($this->pdo, $this->userId, $challengeId);
            $solution = $this->getChallengeSolution($challengeId, $isSolved);
            $flags = $this->getChallengeFlags($challengeId);
            $completedFlagIds = $this->getCompletedFlagIds($challengeId);
            $userPoints = $this->calculateUserPoints($flags, $completedFlagIds);
            $challengePoints = $this->calculateChallengePoints($flags);
            $flagProgress = $this->calculateFlagProgress($flags, $completedFlagIds);
            $hints = $this->getChallengeHints($challengeId, $userPoints);
            $entrypoints = $this->getEntrypointsIfRunning($challengeStatus);
            $elapsedSeconds = $this->challengeHelper->getElapsedSecondsForChallenge($this->pdo,$this->userId,$challengeId);
            $remainingSeconds = $this->getRemainingSecondsForChallenge($challengeId);
            $remainingExtensions = $this->getRemainingExtensionsForChallenge($challengeId);
            $leaderboard = $this->challengeHelper->getSolvedLeaderboard($this->pdo,$challengeId);

            $this->sendResponse([
                'success' => true,
                'challenge' => array_merge($challenge, [
                    'challenge_status' => $challengeStatus,
                    'hints' => $hints,
                    'solution' => $solution,
                    'user_points' => $userPoints,
                    'challenge_points' => $challengePoints,
                    'entrypoints' => $entrypoints,
                    'elapsed_seconds' => $elapsedSeconds,
                    'remaining_seconds' => $remainingSeconds,
                    'remaining_extensions' => $remainingExtensions,
                    'isSolved' => $isSolved,
                    'leaderboard' => $leaderboard,
                    'flags_submitted' => $flagProgress['submitted'],
                    'flags_total' => $flagProgress['total'],
                ])
            ]);
        } catch (CustomException $e) {
            $this->logger->logError("Failed to fetch challenge details - ID: $challengeId, Error: " . $e->getMessage());
            throw $e;
        } catch (Exception $e) {
            $this->logger->logError("Unexpected error fetching challenge details - ID: $challengeId, Error: " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        }
    }

    /**
     * @throws Exception
     */
    private function getChallengeDetails(int $challengeId)
    {
        $stmt = $this->pdo->prepare("
            SELECT
                id,
                name,
                description,
                category,
                difficulty,
                image_path,
                is_active,
                created_at,
                updated_at,
                hint,
                marked_for_deletion,
                creator_username,
                creator_id,
                solve_count
            FROM get_challenge_template_details(:id)
        ");
        $stmt->execute(['id' => $challengeId]);
        $challenge = $stmt->fetch(PDO::FETCH_ASSOC);

        if (!$challenge) {
            $this->logger->logWarning("Challenge not found - ID: $challengeId, User ID: $this->userId");
            throw new CustomException("Challenge not found", 404);
        }

        $challenge['isCreator'] = ($challenge['creator_id'] == $this->userId);
        unset($challenge['creator_id']);

        return $challenge;
    }

    private function getChallengeStatus(int $challengeId)
    {
        $stmt = $this->pdo->prepare("
            SELECT get_challenge_user_status(:user_id, :challenge_id) AS challenge_status
        ");
        $stmt->execute([
            'user_id' => $this->userId,
            'challenge_id' => $challengeId
        ]);
        return $stmt->fetch(PDO::FETCH_ASSOC);
    }

    private function getChallengeSolution($challengeId, $isSolved)
    {
        if ($isSolved) {
            $stmt = $this->pdo->prepare("
                SELECT get_challenge_solution(:challenge_template_id) AS solution
            ");
            $stmt->execute(['challenge_template_id' => $challengeId]);
            $solution = $stmt->fetch(PDO::FETCH_ASSOC);
            return $solution['solution'];
        }
        return "";
    }

    private function getRemainingSecondsForChallenge(int $challengeId)
    {
        $stmt = $this->pdo->prepare("
            SELECT get_remaining_seconds_for_user_challenge(:user_id, :challenge_id) AS remaining_seconds
        ");
        $stmt->execute([
            'user_id' => $this->userId,
            'challenge_id' => $challengeId
        ]);

        $result = $stmt->fetchColumn();
        return $result !== false ? max(0, $result) : 0;
    }

    private function getRemainingExtensionsForChallenge(int $challengeId)
    {
        $stmt = $this->pdo->prepare("
            SELECT get_remaining_extensions_for_user_challenge(:user_id, :challenge_id) AS used_extensions
        ");
        $stmt->execute([
            'user_id' => $this->userId,
            'challenge_id' => $challengeId
        ]);

        $result = $stmt->fetchColumn();
        return $result !== false ? max(0, $this->config['challenge']['MAX_TIME_EXTENSIONS'] - $result) : 0;
    }

    private function getChallengeFlags(int $challengeId): array
    {
        $stmt = $this->pdo->prepare("
            SELECT
                id,
                challenge_template_id,
                flag,
                description,
                points,
                order_index
            FROM get_challenge_flags(:id)
        ");
        $stmt->execute(['id' => $challengeId]);
        return $stmt->fetchAll(PDO::FETCH_ASSOC);
    }

    private function calculateChallengePoints(array $flags): int
    {
        $totalPoints = 0;
        foreach ($flags as $flag) {
            $totalPoints += (int)($flag['points'] ?? 0);
        }
        return $totalPoints;
    }

    private function getChallengeHints(int $challengeId, int $userPoints): array
    {
        $stmt = $this->pdo->prepare("
            SELECT
                id,
                challenge_template_id,
                hint_text,
                unlock_points,
                order_index
            FROM get_unlocked_challenge_hints(:id, :userPoints)
        ");
        $stmt->execute([
            'id' => $challengeId,
            'userPoints' => $userPoints
        ]);
        return $stmt->fetchAll(PDO::FETCH_ASSOC);
    }


    private function getCompletedFlagIds(int $challengeId): array
    {
        $stmt = $this->pdo->prepare("
            SELECT flag_id
            FROM get_completed_flag_ids_for_user(:user_id, :challenge_id)
        ");
        $stmt->execute(['user_id' => $this->userId, 'challenge_id' => $challengeId]);
        return $stmt->fetchAll(PDO::FETCH_COLUMN, 0);
    }

    private function calculateUserPoints(array $flags, array $completedFlagIds)
    {
        $userPoints = 0;
        foreach ($flags as $flag) {
            if (in_array($flag['id'], $completedFlagIds)) {
                $userPoints += $flag['points'];
            }
        }
        return $userPoints;
    }

    private function calculateFlagProgress(array $flags, array $completedFlagIds): array
    {
        $submitted = 0;
        foreach ($flags as $flag) {
            if (in_array($flag['id'], $completedFlagIds)) {
                $submitted++;
            }
        }

        return [
            'submitted' => $submitted,
            'total' => count($flags)
        ];
    }

    private function getEntrypointsIfRunning(array $challengeStatus): array
    {
        if ($challengeStatus['challenge_status'] !== 'running') {
            return [];
        }

        $stmt = $this->pdo->prepare("
            SELECT subnet FROM get_entrypoints_for_user_challenge(:user_id)
        ");
        $stmt->execute(['user_id' => $this->userId]);
        return $stmt->fetchAll(PDO::FETCH_COLUMN, 0);
    }

    /**
     * @throws Exception
     */
    private function checkBadgeUnlocks(int $challengeId): array
    {
        $unlockedBadges = [];

        try {
            $challengeCategory = $this->getChallengeCategory($challengeId);

            if ($this->isFirstBlood($challengeId) && $this->grantBadge(7)) {
                $unlockedBadges[] = 'First Blood';
                $this->logger->logDebug("First Blood badge unlocked - Challenge ID: $challengeId, User ID: $this->userId");
            }

            if ($this->isSpeedRunner($challengeId) && $this->grantBadge(8)) {
                $unlockedBadges[] = 'Speed Runner';
                $this->logger->logDebug("Speed Runner badge unlocked - Challenge ID: $challengeId, User ID: $this->userId");
            }

            $categoryBadge = $this->checkCategoryBadge($challengeCategory);
            if ($categoryBadge) {
                $unlockedBadges[] = $categoryBadge;
                $this->logger->logDebug("Category badge unlocked - Challenge ID: $challengeId, User ID: $this->userId, Badge: $categoryBadge");
            }

            if ($this->isMasterHacker() && $this->grantBadge(9)) {
                $unlockedBadges[] = 'Master Hacker';
                $this->logger->logDebug("Master Hacker badge unlocked - User ID: $this->userId");
            }

            return $unlockedBadges;
        } catch (CustomException $e) {
            $this->logger->logError("Error checking badge unlocks - Challenge ID: $challengeId, User ID: $this->userId, Error: " . $e->getMessage());
            throw new CustomException('Failed to check badge unlocks', 500);
        } catch (Exception $e) {
            $this->logger->logError("Unexpected error checking badge unlocks - Challenge ID: $challengeId, User ID: $this->userId, Error: " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        }
    }

    /**
     * @throws Exception
     */
    private function getChallengeCategory(int $challengeId): string
    {
        $stmt = $this->pdo->prepare("
            SELECT get_category_of_challenge_instance(:challenge_id) AS category
        ");
        $stmt->execute(['challenge_id' => $challengeId]);
        $category = $stmt->fetchColumn();

        if ($category === false) {
            $this->logger->logWarning("Challenge category not found - ID: $challengeId, User ID: $this->userId");
            throw new CustomException("Challenge not found", 404);
        }

        return strtolower($category);
    }

    private function isFirstBlood(int $challengeId): bool
    {
        $stmt = $this->pdo->prepare("
            SELECT is_first_blood(:challenge_id, :user_id) AS is_first_blood
        ");
        $stmt->execute([
            'challenge_id' => $challengeId,
            'user_id' => $this->userId
        ]);
        return $stmt->fetchColumn() == 1;
    }

    private function isSpeedRunner(int $challengeId): bool
    {
        $elapsedSeconds = $this->challengeHelper->getElapsedSecondsForChallenge($this->pdo,$this->userId,$challengeId);
        return $elapsedSeconds <= 300;
    }

    private function checkCategoryBadge(string $challengeCategory)
    {
        $categoryBadges = [
            'web' => ['id' => 1, 'name' => 'Web Warrior'],
            'crypto' => ['id' => 2, 'name' => 'Crypto Expert'],
            'reverse' => ['id' => 3, 'name' => 'Reverse Engineer'],
            'forensic' => ['id' => 4, 'name' => 'Forensic Analyst'],
            'pwn' => ['id' => 5, 'name' => 'Binary Buster'],
            'misc' => ['id' => 6, 'name' => 'Puzzle Master'],
        ];

        if (!isset($categoryBadges[$challengeCategory])) {
            return null;
        }

        $stmt = $this->pdo->prepare("
            SELECT get_user_solved_challenges_in_category(:user_id, :category) AS solved_count
        ");
        $stmt->execute(['user_id' => $this->userId, 'category' => $challengeCategory]);

        return ($stmt->fetchColumn() >= 5) && $this->grantBadge($categoryBadges[$challengeCategory]['id'])
            ? $categoryBadges[$challengeCategory]['name']
            : null;
    }

    private function isMasterHacker(): bool
    {
        $stmt = $this->pdo->prepare("
            SELECT count_user_badges_excluding_one(:user_id, 6) AS badge_count_excluding_master
        ");
        $stmt->execute(['user_id' => $this->userId]);
        return $stmt->fetchColumn() == 0;
    }

    private function grantBadge(int $badgeId): bool
    {
        $stmt = $this->pdo->prepare("SELECT badge_with_id_exists(:badge_id) AS exists");
        $stmt->execute(['badge_id' => $badgeId]);
        if ($stmt->fetchColumn() == 0) {
            $this->logger->logWarning("Attempt to grant non-existent badge - Badge ID: $badgeId, User ID: $this->userId");
            return false;
        }

        $stmt = $this->pdo->prepare("
            SELECT user_already_has_badge(:user_id, :badge_id) AS has_badge
            
        ");
        $stmt->execute(['user_id' => $this->userId, 'badge_id' => $badgeId]);

        if ($stmt->fetchColumn() == 0) {
            $stmt = $this->pdo->prepare("
                SELECT award_badge_to_user(:user_id, :badge_id)
            ");
            $stmt->execute(['user_id' => $this->userId, 'badge_id' => $badgeId]);
            $this->logger->logDebug("Badge granted - Badge ID: $badgeId, User ID: $this->userId");
            return true;
        } else {
            return false;
        }
    }

    /**
     * @throws Exception
     */
    private function handleTimeExtension(int $challengeId): void
    {
        $this->pdo->beginTransaction();

        try {

            $stmt = $this->pdo->prepare("
                SELECT 
                    id,
                    used_extensions
                FROM get_id_and_used_extensions_of_running_challenge(:user_id, :challenge_id)
            ");
            $stmt->execute([
                'user_id' => $this->userId,
                'challenge_id' => $challengeId
            ]);

            $challenge = $stmt->fetch();

            if (!$challenge) {
                $this->logger->logWarning("Attempt to extend non-running challenge - ID: $challengeId, User ID: $this->userId");
                throw new CustomException("You don't have this challenge running", 400);
            }

            if ($challenge['used_extensions'] >= $this->config['challenge']['MAX_TIME_EXTENSIONS']) {
                $this->logger->logWarning("Attempt to extend challenge without used_extensions left - ID: $challengeId, User ID: $this->userId");
                throw new CustomException("You cannot extend this challenge any longer", 400);
            }

            $stmt = $this->pdo->prepare("
                SELECT extend_user_challenge_time(:challenge_id, :extend_scalar)
            ");
            $stmt->execute([
                'challenge_id' => $challenge['id'],
                'extend_scalar' => $this->config['challenge']['EXTENSION_HOURS']
            ]);

            $remainingSeconds = $this->getRemainingSecondsForChallenge($challengeId);
            $remainingExtensions = $this->getRemainingExtensionsForChallenge($challengeId);

            $this->pdo->commit();
            $this->logger->logDebug("Challenge time extended - ID: $challengeId, User ID: $this->userId");

            $this->sendResponse([
                'success' => true,
                'message' => 'Challenge time extended by 1 hour',
                'remaining_seconds' => $remainingSeconds,
                'remaining_extensions' => $remainingExtensions
            ]);
        } catch (CustomException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Failed to extend challenge time - ID: $challengeId, Error: " . $e->getMessage());
            throw $e;
        } catch (Exception $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Unexpected error extending challenge time - ID: $challengeId, Error: " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        }
    }

    private function handleError(Exception $e): void
    {
        $errorCode = $e->getCode() ?: 500;
        http_response_code($errorCode);

        $response = [
            'success' => false,
            'message' => $e->getMessage(),
            'error_code' => $errorCode
        ];

        if ($errorCode === 400) {
            $response['error_details'] = [
                'allowed_actions' => $this->config['challenge']['ALLOWED_ACTIONS']
            ];
        }

        $this->logger->logError("ChallengeAPI error [$errorCode]: " . $e->getMessage());
        $this->sendResponse($response);
    }

    private function sendResponse(array $response): void
    {
        echo json_encode($response);
    }
}

// @codeCoverageIgnoreStart

if(defined('PHPUNIT_RUNNING'))
    return;

try {
    header('Content-Type: application/json');
    $config = require __DIR__ . '/../config/backend.config.php';

    $api = new ChallengeHandler(config: $config);
    $api->handleRequest();
} catch (CustomException $e) {
    $errorCode = (int)($e->getCode() ?: 500);
    http_response_code($errorCode);
    $logger = new Logger("/challenge");
    $logger->logError("Error in challenge endpoint: " . $e->getMessage() . " (Code: $errorCode)");
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
    $logger = new Logger("/challenge");
    $logger->logError("Unexpected error in challenge endpoint: " . $e->getMessage());
    echo json_encode([
        'success' => false,
        'message' => 'An unexpected error occurred'
    ]);
}

// @codeCoverageIgnoreEnd