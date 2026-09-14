<?php
declare(strict_types=1);

require_once __DIR__ . '/../vendor/autoload.php';

class OvaUploadHandler
{
    private PDO $pdo;
    private int $userId;
    private string $action;
    private array $inputData;
    private array $config;
    private array $generalConfig;
    private string $route;

    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ILogger $logger;
    private ICurlHelper $curlHelper;
    private IAuthHelper $authHelper;
    private IOvaValidator $ovaValidator;

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
        array $config,
        array $generalConfig,

        IDatabaseHelper $databaseHelper = null,
        ISecurityHelper $securityHelper = null,
        ILogger $logger = null,
        ICurlHelper $curlHelper = null,
        IAuthHelper $authHelper = null,
        IOvaValidator $ovaValidator = null,

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
        $this->route = "upload-diskfile";

        $this->databaseHelper = $databaseHelper ?? new DatabaseHelper($logger, $system);
        $this->securityHelper = $securityHelper ?? new SecurityHelper($logger, $session, $system);
        $this->logger = $logger ?? new Logger(route: $this->route, system: $system);
        $this->curlHelper = $curlHelper ?? new CurlHelper($env);
        $this->authHelper = $authHelper ?? new AuthHelper($logger, $system, $env);
        $this->ovaValidator = $ovaValidator ?? new OvaValidator($config, $logger, $system);

        $this->system = $system;

        $this->config = $config;
        $this->generalConfig = $generalConfig;
        $this->pdo = $this->databaseHelper->getPDO();
        $this->initSession();
        $this->validateAccess();
        $this->userId = $this->session['user_id'];
        $this->action = $this->get['action'] ?? '';
        $this-> inputData = $this->parseInputData();

        $this->logger->logDebug("Initialized OvaUploadHandler for User ID: $this->userId, Action: $this->action");
    }

    private function initSession(): void
    {
        try {
            $this->securityHelper->initSecureSession();
        } catch (CustomException $e) {
            $this->logger->logError("Session initialization failed: " . $e->getMessage());
            throw new CustomException('Session initialization error', 500);
        } catch (Exception $e) {
            $this->logger->logError("Unexpected error during session initialization: " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        }
    }

    /**
     * @throws Exception
     */
    private function validateAccess(): void
    {
        if (!$this->securityHelper->validateSession()) {
            $this->logger->logWarning("Unauthorized access attempt from IP: " . $this->logger->anonymizeIp($this->server['REMOTE_ADDR'] ?? 'unknown'));
            throw new CustomException('Unauthorized - Please login', 401);
        }

        $csrfToken = $this->cookie['csrf_token'] ?? '';
        if (!$this->securityHelper->validateCsrfToken($csrfToken)) {
            $this->logger->logWarning("Invalid CSRF token from user ID: " . ($this->session['user_id'] ?? 'unknown'));
            throw new CustomException('Invalid CSRF token', 403);
        }

        if (!$this->securityHelper->validateAdminAccess($this->pdo)) {
            $this->logger->logWarning("Unauthorized admin access attempt by user ID: " . ($this->session['user_id'] ?? 'unknown'));
            throw new CustomException('Unauthorized - Admin access required', 403);
        }
    }

    private function parseInputData(): array
    {
        if ($this->server['REQUEST_METHOD'] === 'GET') {
            return [];
        }

        if ($this->server['REQUEST_METHOD'] === 'DELETE') {
            $data = json_decode($this->system->file_get_contents('php://input'), true);
            if (json_last_error() !== JSON_ERROR_NONE) {
                $this->logger->logError("Invalid JSON in OVA deletion - User ID: $this->userId");
                throw new CustomException('Invalid JSON data', 400);
            }
            return $data;
        }

        $jsonInput = json_decode($this->system->file_get_contents('php://input'), true);
        if ($jsonInput !== null) {
            return array_merge($this->post->all(), $jsonInput);
        }

        return $this->post->all();
    }

    public function handleRequest(): void
    {
        try {
            $this->ensureUploadDirectory();

            switch ($this->server['REQUEST_METHOD']) {
                case 'POST':
                    $this->handlePostRequest();
                    break;
                case 'GET':
                case 'DELETE':
                    $this->handleGetOrDeleteRequest();
                    break;
                default:
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

    private function ensureUploadDirectory(): void
    {
        if (!$this->system->file_exists($this->config['upload']['UPLOAD_TEMP_DIR']) && !$this->system->mkdir($this->config['upload']['UPLOAD_TEMP_DIR'], 0755, true)) {
            $this->logger->logError("Failed to create upload directory: " . $this->config['upload']['UPLOAD_TEMP_DIR']);
            throw new CustomException('System configuration error', 500);
        }
    }

    /**
     * @throws Exception
     */
    private function handlePostRequest(): void
    {
        $uploadType = isset($this->inputData['uploadId']) ? 'chunked' : 'direct';
        $this->logger->logDebug("Upload initiated by user $this->userId, type: $uploadType");

        if ($uploadType === 'chunked') {
            $this->handleChunkedUpload();
        } else {
            $this->handleDirectUpload();
        }
    }

    /**
     * @throws Exception
     */
    private function handleChunkedUpload(): void
    {
        $phase = $this->inputData['phase'] ??
            (isset($this->files['chunk']) ? 'chunk' :
                (isset($this->inputData['fileName']) ? 'init' : 'finalize'));

        switch ($phase) {
            case 'init':
                $this->handleChunkedInit();
                break;
            case 'chunk':
                $this->handleChunkUpload();
                break;
            case 'finalize':
                $this->handleChunkedFinalize();
                break;
            case 'cancel':
                $this->handleUploadCancellation();
                break;
            default:
                throw new CustomException('Invalid upload request', 400);
        }
    }

    private function validateGuestOS(string $guestOs): void
    {
        if (!in_array($guestOs, ['linux', 'windows'], true)) {
            $this->logger->logWarning("Invalid guest OS value '$guestOs' from user $this->userId");
            throw new CustomException('Invalid guest OS specified', 400);
        }
    }

    private function handleChunkedInit(): void
    {
        $fileName = $this->sanitizeFilename($this->inputData['fileName']);
        $fileSize = (int)($this->inputData['fileSize'] ?? 0);
        $totalChunks = (int)($this->inputData['totalChunks'] ?? 0);
        $guestOs = $this->inputData['guest_os'] ?? '';

        $this->logger->logDebug("Chunked upload init for user $this->userId: $fileName ($fileSize bytes)");

        $this->validateFileSize($fileSize);
        $this->validateFileType($fileName);
        $this->validateGuestOS($guestOs);

        $displayName = $this->system->pathinfo($fileName, PATHINFO_FILENAME);
        $this->checkDuplicateFileName($displayName);

        $uploadId = uniqid('upload_');
        $this->createUploadMetadata($uploadId, $fileName, $fileSize, $totalChunks, $guestOs);

        echo json_encode([
            'success' => true,
            'uploadId' => $uploadId,
            'chunkSize' => $this->generalConfig['upload']['CHUNK_SIZE']
        ]);
        defined('PHPUNIT_RUNNING') || exit;
    }

    private function handleChunkUpload(): void
    {
        $uploadId = $this->inputData['uploadId'];
        $chunkIndex = (int)$this->inputData['chunkIndex'];
        $chunkSize = $this->generalConfig['upload']['CHUNK_SIZE'];
        $tempFile = $this->config['upload']['UPLOAD_TEMP_DIR'] . $uploadId;

        $meta = $this->validateUploadSession($uploadId);

        $chunkTmpName = $this->files['chunk']['tmp_name'];
        $chunkData = $this->system->file_get_contents($chunkTmpName);
        if ($chunkData === false) {
            $this->logger->logError("Failed to read uploaded chunk $chunkIndex for upload $uploadId");
            throw new CustomException('File read failed', 500);
        }

        $combinedFile = $tempFile . '.combined';
        $out = $this->system->fopen($combinedFile, 'c+b');
        if (!$out) {
            $this->logger->logError("Failed to open combined file for writing chunk $chunkIndex of upload $uploadId");
            throw new CustomException('File open failed', 500);
        }

        $offset = $chunkIndex * $chunkSize;
        if ($this->system->fseek($out, $offset) !== 0) {
            $this->system->fclose($out);
            $this->logger->logError("fseek failed for chunk $chunkIndex at offset $offset in upload $uploadId");
            throw new CustomException('File seek failed', 500);
        }

        if ($this->system->fwrite($out, $chunkData) === false) {
            $this->system->fclose($out);
            $this->logger->logError("Failed to write chunk $chunkIndex at offset $offset for upload $uploadId");
            throw new CustomException('File write failed', 500);
        }

        $this->system->fclose($out);

        $this->updateUploadMetadata($uploadId, $meta);

        echo json_encode(['success' => true]);
        defined('PHPUNIT_RUNNING') || exit;
    }

    /**
     * @throws Exception
     */
    private function handleChunkedFinalize(): void
    {
        $uploadId = $this->inputData['uploadId'];
        $tempFile = $this->config['upload']['UPLOAD_TEMP_DIR'] . $uploadId;
        $proxmoxFilename = null;

        try {
            $meta = $this->validateUploadSession($uploadId);
            $this->verifyAllChunksReceived($uploadId, $meta);

            $combinedFile = $tempFile . '.combined';

            if (!$this->system->file_exists($combinedFile)) {
                $this->logger->logError("Combined file missing for upload $uploadId");
                throw new CustomException('Combined file missing', 500);
            }

            $this->validateOvaFile($combinedFile);

            $uniqueName = uniqid('ova_') . '.' . $this->system->pathinfo($meta['fileName'], PATHINFO_EXTENSION);
            $proxmoxFilename = $uniqueName;

            $this->uploadToProxmox(
                $combinedFile,
                $this->system->pathinfo($meta['fileName'], PATHINFO_FILENAME),
                $uniqueName,
                $meta['guest_os']
            );

            $this->cleanupUploadFiles($uploadId, $combinedFile);

            $this->logger->logInfo("Chunked upload $uploadId completed successfully");

            echo json_encode([
                'success' => true,
                'message' => 'File uploaded successfully'
            ]);
        } catch (CustomException $e) {
            if ($proxmoxFilename) {
                try {
                    $this->deleteFromProxmox($proxmoxFilename);
                } catch (CustomException $deleteEx) {
                    $this->logger->logError("Failed to clean up Proxmox file during finalize: " . $deleteEx->getMessage());
                } catch (Exception $deleteEx) {
                    $this->logger->logError("Unexpected error during Proxmox file cleanup: " . $deleteEx->getMessage());
                }
            }

            $this->cleanupPartialUpload($uploadId);

            throw $e;
        }
    }

    private function handleUploadCancellation(): void
    {
        $uploadId = $this->inputData['uploadId'];

        $metaFile = $this->config['upload']['UPLOAD_TEMP_DIR'] . $uploadId . '.meta';
        if (!$this->system->file_exists($metaFile)) {
            echo json_encode(['success' => true]);

            if (defined('PHPUNIT_RUNNING'))
                return;
            // @codeCoverageIgnoreStart
            else
                exit;
            // @codeCoverageIgnoreEnd
        }

        $meta = json_decode($this->system->file_get_contents($metaFile), true);
        if ($meta['userId'] !== $this->userId) {
            $this->logger->logWarning("User $this->userId attempted to cancel another user's upload");
            throw new CustomException('Unauthorized cancellation', 403);
        }

        $proxmoxFilename = $meta['proxmoxFilename'] ?? null;
        $this->cleanupPartialUpload($uploadId);

        if ($proxmoxFilename) {
            try {
                $this->deleteFromProxmox($proxmoxFilename);
            } catch (CustomException $e) {
                $this->logger->logError("Failed to delete Proxmox file during cancellation: " . $e->getMessage());
            } catch (Exception $e) {
                $this->logger->logError("Unexpected error during Proxmox file deletion: " . $e->getMessage());
            }
        }

        echo json_encode(['success' => true]);
        defined('PHPUNIT_RUNNING') || exit;
    }

    private function cleanupPartialUpload(string $uploadId): void
    {
        $files = [
            $this->config['upload']['UPLOAD_TEMP_DIR'] . $uploadId . '.combined',
            $this->config['upload']['UPLOAD_TEMP_DIR'] . $uploadId . '.meta',
            ...$this->system->glob($this->config['upload']['UPLOAD_TEMP_DIR'] . $uploadId . '.part*')
        ];

        foreach ($files as $file) {
            if ($this->system->file_exists($file)) {
                try {
                    $this->system->unlink($file);
                } catch (CustomException $e) {
                    $this->logger->logError("Failed to delete $file: " . $e->getMessage());
                } catch (Exception $e) {
                    $this->logger->logError("Unexpected error deleting $file: " . $e->getMessage());
                }
            }
        }
    }

    /**
     * @throws Exception
     */
    private function handleDirectUpload(): void
    {
        if (!isset($this->files['ova_file']) || $this->files['ova_file']['error'] !== UPLOAD_ERR_OK) {
            $errorCode = $this->files['ova_file']['error'] ?? 'unknown';

            if ($errorCode === UPLOAD_ERR_PARTIAL) {
                $this->logger->logWarning("Upload cancelled/timed out for user $this->userId");
                throw new CustomException('Upload was cancelled or timed out', 400);
            }

            $this->logger->logError("File upload error $errorCode for user $this->userId");
            throw new CustomException('File upload failed', 400);
        }

        $file = $this->files['ova_file'];
        $guestOs = $this->post['guest_os'] ?? '';
        $tempPath = '';
        $uniqueName = '';

        try {
            $this->validateFileType($file['name']);
            $this->validateFileSize($file['size']);
            $this->validateGuestOS($guestOs);

            $originalName = $this->system->pathinfo($this->sanitizeFilename($file['name']), PATHINFO_FILENAME);
            $uniqueName = uniqid('ova_') . '.' . strtolower($this->system->pathinfo($file['name'], PATHINFO_EXTENSION));
            $tempPath = $this->system->sys_get_temp_dir() . '/' . $uniqueName;

            $this->system->ignore_user_abort(false);

            if (!$this->system->move_uploaded_file($file['tmp_name'], $tempPath)) {
                throw new CustomException('File processing error', 500);
            }

            if ($this->system->connection_aborted()) {
                $this->logger->logWarning("Client disconnected during direct upload processing");
                @$this->system->unlink($tempPath);
                throw new CustomException('Upload cancelled', 400);
            }

            $this->validateOvaFile($tempPath);
            $this->uploadToProxmox($tempPath, $originalName, $uniqueName, $guestOs);

            if ($this->system->connection_aborted()) {
                $this->logger->logWarning("Client disconnected during direct upload processing");
                @$this->system->unlink($tempPath);
                throw new CustomException('Upload cancelled', 400);
            }

            $this->logger->logInfo("OVA upload completed successfully for user $this->userId");
            echo json_encode([
                'success' => true,
                'message' => 'File uploaded successfully'
            ]);
        } catch (CustomException $e) {
            if (!empty($uniqueName) && $e->getCode() !== 400) {
                try {
                    $this->deleteFromProxmox($uniqueName);
                } catch (CustomException $deleteEx) {
                    $this->logger->logError("Failed to clean up Proxmox file $uniqueName: " . $deleteEx->getMessage());
                } catch (Exception $deleteEx) {
                    $this->logger->logError("Unexpected error during Proxmox cleanup of $uniqueName: " . $deleteEx->getMessage());
                }
            }

            if ($tempPath && $this->system->file_exists($tempPath)) {
                @$this->system->unlink($tempPath);
            }

            throw $e;
        } finally {
            if ($tempPath && $this->system->file_exists($tempPath)) {
                @$this->system->unlink($tempPath);
            }
        }
    }

    private function handleGetOrDeleteRequest(): void
    {
        switch ($this->action) {
            case 'list':
                $this->handleListAction();
                break;
            case 'delete':
                $this->handleDeleteAction();
                break;
            default:
                throw new CustomException('Invalid request', 400);
        }
    }

    private function handleListAction(): void
    {
        try {
            $stmt = $this->pdo->prepare("
                SELECT
                    id, 
                    display_name, 
                    upload_date,
                    guest_os
                FROM get_user_disk_files(:user_id)
            ");
            $stmt->execute(['user_id' => $this->userId]);
            $ovas = $stmt->fetchAll(PDO::FETCH_ASSOC);
        } catch (PDOException $e) {
            $this->logger->logError("Database error listing files for user $this->userId: " . $e->getMessage());
            throw new CustomException('Could not retrieve file list', 500);
        }
        echo json_encode([
            'success' => true,
            'ovas' => $ovas
        ]);
    }

    private function handleDeleteAction(): void
    {
        $ovaId = $this->inputData['ova_id'] ?? null;
        if (!$ovaId) {
            throw new CustomException('Missing file ID', 400);
        }

        $proxmox_filename = $this->getOvaForDeletion($ovaId);
        $this->deleteFromProxmox($proxmox_filename);
        $this->deleteFromDatabase($ovaId);

        $this->logger->logDebug("Successfully deleted OVA $ovaId for user $this->userId");
        echo json_encode([
            'success' => true,
            'message' => 'File deleted successfully'
        ]);
    }

    private function validateFileSize(int $fileSize): void
    {
        if ($fileSize > $this->generalConfig['upload']['MAX_FILE_SIZE']) {
            throw new CustomException('File too large', 400);
        }
    }

    private function validateFileType(string $fileName): void
    {
        $fileExt = strtolower($this->system->pathinfo($fileName, PATHINFO_EXTENSION));
        if (!in_array("." . $fileExt, $this->generalConfig['upload']['VALID_FILE_TYPES'])) {
            $this->logger->logError("Invalid file type attempt by user $this->userId: $fileExt");
            throw new CustomException('Invalid file type', 400);
        }
    }

    private function checkDuplicateFileName(string $displayName): void
    {
        try {
            $stmt = $this->pdo->prepare("
                SELECT is_duplicate_file_name(:user_id, :display_name) AS count
            ");
            $stmt->execute([
                'user_id' => $this->userId,
                'display_name' => $displayName
            ]);
            $result = $stmt->fetchColumn();
        } catch (PDOException $e) {
            $this->logger->logError("Database error checking duplicate file name: " . $e->getMessage());
            throw new CustomException('Could not verify file name', 500);
        }

        if ($result != 0) {
            $this->logger->logError("Duplicate file name attempt by user $this->userId: $displayName");
            throw new CustomException('File name already exists', 400);
        }
    }

    private function createUploadMetadata(string $uploadId, string $fileName, int $fileSize, int $totalChunks, string $guestOs): void
    {
        $metadata = [
            'fileName' => $fileName,
            'fileSize' => $fileSize,
            'totalChunks' => $totalChunks,
            'receivedChunks' => 0,
            'userId' => $this->userId,
            'uploadDate' => $this->system->time(),
            'guest_os' => $guestOs
        ];

        if ($this->system->file_put_contents($this->config['upload']['UPLOAD_TEMP_DIR'] . $uploadId . '.meta', json_encode($metadata)) === false) {
            $this->logger->logError("Failed to create upload metadata file for upload $uploadId");
            throw new CustomException('Could not initialize upload', 500);
        }
    }

    private function validateUploadSession(string $uploadId): array
    {
        $metaFile = $this->config['upload']['UPLOAD_TEMP_DIR'] . $uploadId . '.meta';
        if (!$this->system->file_exists($metaFile)) {
            throw new CustomException('Upload session expired', 404);
        }

        $meta = json_decode($this->system->file_get_contents($metaFile), true);
        if ($meta['userId'] !== $this->userId) {
            $this->logger->logError("User ID mismatch in chunk upload: $this->userId vs {$meta['userId']}");
            throw new CustomException('Upload session mismatch', 403);
        }

        return $meta;
    }

    private function updateUploadMetadata(string $uploadId, array $meta): void
    {
        $meta['receivedChunks']++;
        if ($this->system->file_put_contents($this->config['upload']['UPLOAD_TEMP_DIR'] . $uploadId . '.meta', json_encode($meta)) === false) {
            $this->logger->logError("Failed to update metadata for upload $uploadId");
            throw new CustomException('Could not update upload status', 500);
        }
    }

    private function verifyAllChunksReceived(string $uploadId, array $meta): void
    {
        if ($meta['receivedChunks'] !== $meta['totalChunks']) {
            $this->logger->logError("Missing chunks in upload $uploadId: received {$meta['receivedChunks']} of {$meta['totalChunks']}");
            throw new CustomException('Upload incomplete', 400);
        }
    }

    /**
     * @throws Exception
     */
    private function validateOvaFile(string $filePath): void
    {
        try {
            $this->ovaValidator->validate($filePath);
        } catch (CustomException $e) {
            @$this->system->unlink($filePath);
            $this->logger->logError("OVA validation failed: " . $e->getMessage());
            throw $e;
        } catch (Exception $e) {
            @$this->system->unlink($filePath);
            $this->logger->logError("Unexpected error during OVA validation: " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        }
    }

    private function cleanupUploadFiles(string $uploadId, string $finalPath): void
    {
        $this->system->unlink($finalPath);
        $this->system->unlink($this->config['upload']['UPLOAD_TEMP_DIR'] . $uploadId . '.meta');
    }

    private function uploadToProxmox(string $filePath, string $displayName, string $proxmoxFilename, string $guestOs): void
    {

        $this->checkDuplicateFileName($displayName);

        $endpoint = "/api2/json/nodes/" . $this->env['PROXMOX_HOSTNAME'] . "/storage/local/upload";
        $postParams = [
            'content' => 'import',
            'filename' => new CURLFile(
                $filePath,
                'application/octet-stream',
                $proxmoxFilename
            )
        ];

        $authHeaders = $this->authHelper->getAuthHeaders("multipart/form-data");
        $result = $this->curlHelper->makeCurlRequest($endpoint, 'POST', $authHeaders, $postParams);

        if (!$result) {
            $this->logger->logError("Proxmox API connection failed for user $this->userId");
            $this->logger->logDebug("Triesd to upload file $proxmoxFilename for user $this->userId with display name $displayName, auth headers: " . print_r($authHeaders, true) . " and post params: " . print_r($postParams, true));
            $this->logger->logDebug("Got curl result: " . print_r($result, true));
            throw new CustomException('Server connection failed', 500);
        }

        $responseData = json_decode($result['response'], true);
        $httpCode = $result['http_code'];

        if ($httpCode !== 200) {
            $error = $responseData['errors'] ?? 'Unknown error';
            $this->logger->logError("Proxmox upload failed for user $this->userId: HTTP $httpCode - " . json_encode($error));
            $this->logger->logDebug("Triesd to upload file $proxmoxFilename for user $this->userId with display name $displayName, auth headers: " . json_encode($authHeaders) . " and post params: " . json_encode($postParams));
            throw new CustomException('File processing failed', 500);
        }

        $this->storeFileMetadata($displayName, $proxmoxFilename, $guestOs);
    }

    private function storeFileMetadata(string $displayName, string $proxmoxFilename, string $guestOs): void
    {
        $this->pdo->beginTransaction();
        try {
            $stmt = $this->pdo->prepare("
                SELECT add_user_disk_file(:user_id, :display_name, :proxmox_filename, :guest_os)
            ");
            $stmt->execute([
                'user_id' => $this->userId,
                'display_name' => $displayName,
                'proxmox_filename' => $proxmoxFilename,
                'guest_os' => $guestOs
            ]);
            $this->pdo->commit();
        } catch (PDOException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Database error saving file metadata: " . $e->getMessage());
            throw new CustomException('Could not save file information', 500);
        }
    }

    private function getOvaForDeletion(string $ovaId): string
    {
        try {
            $stmt = $this->pdo->prepare("
                SELECT get_filename_by_id(:ova_id, :user_id) AS proxmox_filename
            ");
            $stmt->execute(['ova_id' => $ovaId, 'user_id' => $this->userId]);
            $proxmox_filename = $stmt->fetchColumn();

            if (!$proxmox_filename) {
                $this->logger->logError("Delete attempt for non-existent OVA $ovaId by user $this->userId");
                throw new CustomException('File not found', 404);
            }

            return $proxmox_filename;

        } catch (PDOException $e) {
            $this->logger->logError("Database error fetching OVA $ovaId for deletion: " . $e->getMessage());
            throw new CustomException('Could not retrieve file information', 500);
        }
    }

    private function deleteFromProxmox(string $proxmoxFilename): void
    {
        $endpoint = "/api2/json/nodes/" . $this->env['PROXMOX_HOSTNAME'] . "/storage/local/content/import/" . urlencode($proxmoxFilename);
        $authHeaders = $this->authHelper->getAuthHeaders();
        $result = $this->curlHelper->makeCurlRequest($endpoint, 'DELETE', $authHeaders);

        if (!$result || $result['http_code'] !== 200) {
            $this->logger->logError("Proxmox delete failed for file $proxmoxFilename by user $this->userId");
            throw new CustomException('File deletion failed', 500);
        }
    }

    private function deleteFromDatabase(string $ovaId): void
    {
        try {
            $stmt = $this->pdo->prepare("
                SELECT delete_user_disk_file(:ova_id, :user_id)
            ");
            $stmt->execute(['ova_id' => $ovaId, 'user_id' => $this->userId]);
        } catch (PDOException $e) {
            $this->logger->logError("Database error deleting OVA $ovaId: " . $e->getMessage());
            throw new CustomException('Could not complete file deletion', 500);
        }
    }

    private function sanitizeFilename(string $filename): string
    {
        return preg_replace('/[^a-zA-Z0-9\-_. ]/', '', $filename);
    }

    private function handleError(Exception $e): void
    {
        $code = $e->getCode() >= 400 && $e->getCode() < 600 ? $e->getCode() : 500;
        http_response_code($code);

        $this->logger->logError("OVA route error [$code]: " . $e->getMessage() . " | User: $this->userId | Action: $this->action");

        echo json_encode([
            'success' => false,
            'message' => $e->getMessage(),
            'error_code' => $code,
            'redirect' => $code === 401 ? '/login' : null
        ]);
        defined('PHPUNIT_RUNNING') || exit;
    }
}

// @codeCoverageIgnoreStart

if(defined('PHPUNIT_RUNNING'))
    return;

try {
    $config = require __DIR__ . '/../config/backend.config.php';
    $system = new SystemWrapper();
    $generalConfig = json_decode($system->file_get_contents(__DIR__ . '/../config/general.config.json'), true);

    $handler = new OvaUploadHandler(config: $config, generalConfig: $generalConfig);
    $handler->handleRequest();
} catch (CustomException $e) {
    $errorCode = $e->getCode() ?: 500;
    http_response_code($errorCode);
    $logger = new Logger("/upload-diskfile");
    $logger->logError("Error in upload-diskfile endpoint: " . $e->getMessage() . " (Code: $errorCode)");
    $response = [
        'success' => false,
        'message' => $e->getMessage()
    ];

    if ($errorCode === 401) {
        $response['redirect'] = '/login';
    }

    echo json_encode($response);
} catch (Exception $e) {
    // most likely not reachable, gonna leave it here for safety
    http_response_code(500);
    $logger = new Logger("/upload-diskfile");
    $logger->logError("Unexpected error in upload-diskfile endpoint: " . $e->getMessage());
    echo json_encode([
        'success' => false,
        'message' => 'Unexpected server error'
    ]);
}

// @codeCoverageIgnoreEnd