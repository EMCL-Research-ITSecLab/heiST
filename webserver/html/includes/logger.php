<?php
declare(strict_types=1);

require_once __DIR__ . '/../vendor/autoload.php';

class Logger implements ILogger
{
    private string $errorLogFile;
    private string $infoLogFile;
    private string $debugLogFile;
    private string $warningLogFile;
    private string $route;

    private ISystem $system;

    public function __construct(
        string $route,
        string $errorLogFile = '/var/log/heiST/api_errors.log',
        string $infoLogFile = '/var/log/heiST/api_info.log',
        string $debugLogFile = '/var/log/heiST/api_debug.log',
        string $warningLogFile = '/var/log/heiST/api_warning.log',
        ISystem $system = new SystemWrapper()
    )
    {
        $this->route = $route;
        $this->errorLogFile = $errorLogFile;
        $this->infoLogFile = $infoLogFile;
        $this->debugLogFile = $debugLogFile;
        $this->warningLogFile = $warningLogFile;

        $this->system = $system;
    }

    private function formatLogMessage(string $level, string $message): string
    {
        $timestamp = $this->system->date("Y-m-d H:i:s");
        $remoteAddr = $_SERVER['REMOTE_ADDR'] ?? 'unknown';
        $httpMethod = $_SERVER['REQUEST_METHOD'] ?? 'CLI';

        return sprintf(
            "[%s] [%s] [%s] [%s] [%s] : %s\n",
            $timestamp,
            strtoupper($level),
            $this->route,
            $httpMethod,
            $this->anonymizeIp($remoteAddr),
            $message
        );
    }

    public function logError($message): void
    {
        $this->system->file_put_contents(
            $this->errorLogFile,
            $this->formatLogMessage('error', $message),
            FILE_APPEND
        );
    }

    public function logInfo($message): void
    {
        $this->system->file_put_contents(
            $this->infoLogFile,
            $this->formatLogMessage('info', $message),
            FILE_APPEND
        );
    }

    public function logDebug($message): void
    {
        $this->system->file_put_contents(
            $this->debugLogFile,
            $this->formatLogMessage('debug', $message),
            FILE_APPEND
        );
    }

    public function logWarning($message): void
    {
        $this->system->file_put_contents(
            $this->warningLogFile,
            $this->formatLogMessage('warning', $message),
            FILE_APPEND
        );
    }

    public function anonymizeIp(string $ip): string
    {
        #if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
        #    return preg_replace('/\.\d+$/', '.xxx', $ip);
        #}
        #if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV6)) {
        #    return preg_replace('/:[^:]+$/', ':xxxx', $ip);
        #}
        #return 'invalid-ip';
        return $ip;
    }
}