<?php
declare(strict_types=1);

require_once __DIR__ . '/../vendor/autoload.php';

class CurlHelper implements ICurlHelper
{
    private IEnv $env;

    private string $route;

    public function __construct(IEnv $env)
    {
        $this->env = $env;
        $this->route = "/curlHelper";
    }

    public function makeCurlRequest($endpoint, $method = 'GET', $headers = [], $postFields = null): bool|array
    {
        $baseUrl = 'https://' . $this->env['PROXMOX_HOSTNAME'];
        if (isset($this->env['PROXMOX_PORT'])) {
            $baseUrl .= ":" . $this->env['PROXMOX_PORT'];
        }

        $url = $baseUrl . '/' . ltrim($endpoint, '/');

        $ch = curl_init($url);
        $defaultOptions = [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
            CURLOPT_HTTPHEADER => $headers
        ];

        if ($method === 'POST') {
            if ($postFields !== null) {
                $defaultOptions[CURLOPT_POST] = true;
                $defaultOptions[CURLOPT_POSTFIELDS] = $postFields;
            } else {
                $defaultOptions[CURLOPT_CUSTOMREQUEST] = 'POST';
            }
        } elseif (in_array($method, ['DELETE', 'PUT', 'GET'])) {
            $defaultOptions[CURLOPT_CUSTOMREQUEST] = $method;
        }

        curl_setopt_array($ch, $defaultOptions);

        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);

        curl_close($ch);
        if ($response === false) {
            $logger = new Logger(route: $this->route);
            $logger->logDebug("cURL error " . curl_error($ch));

            return false;
        }

        return ['response' => $response, 'http_code' => $httpCode];
    }

    public function makeBackendRequest($endpoint, $method = 'GET', $headers = [], $postFields = null): array
    {
        $baseUrl = 'https://' . rtrim($this->env['BACKEND_HOST'], '/');
        if (isset($this->env['BACKEND_PORT'])) {
            $baseUrl .= ":" . $this->env['BACKEND_PORT'];
        }

        $url = $baseUrl . '/' . ltrim($endpoint, '/');

        $ch = curl_init($url);
        $defaultOptions = [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 3,
            CURLOPT_TIMEOUT => 15,
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_HEADERFUNCTION => function ($curl, $header) use (&$headers) {
                $parts = explode(':', $header, 2);
                if (count($parts) === 2) {
                    $headers[strtolower(trim($parts[0]))] = trim($parts[1]);
                }
                return strlen($header);
            }
        ];

        if ($method === 'POST') {
            if ($postFields !== null) {
                $defaultOptions[CURLOPT_POST] = true;
                $defaultOptions[CURLOPT_POSTFIELDS] = is_array($postFields)
                    ? json_encode($postFields)
                    : $postFields;
            } else {
                $defaultOptions[CURLOPT_CUSTOMREQUEST] = 'POST';
            }
        } elseif (in_array($method, ['DELETE', 'PUT', 'GET'])) {
            $defaultOptions[CURLOPT_CUSTOMREQUEST] = $method;
        }

        curl_setopt_array($ch, $defaultOptions);

        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error = curl_error($ch);
        curl_close($ch);

        return [
            'success' => $response !== false && $httpCode < 400,
            'response' => $response,
            'http_code' => $httpCode,
            'error' => $error ?: null,
            'headers' => $headers
        ];
    }
}
