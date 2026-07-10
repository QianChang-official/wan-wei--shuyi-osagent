[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:8010',
    [string]$ApiKey = 'wanwei-dev-key'
)

$ErrorActionPreference = 'Stop'
$headers = @{ 'X-API-Key' = $ApiKey }

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

$health = Invoke-RestMethod -Uri "$BaseUrl/health" -Method Get
Assert-True ($health.status -eq 'ok') 'Health check did not return status=ok.'

$console = Invoke-WebRequest -Uri "$BaseUrl/console/" -UseBasicParsing
Assert-True ($console.StatusCode -eq 200) 'Console did not return HTTP 200.'
Assert-True ($console.Content -match '<div id="app"></div>') 'Console index is not the expected Vue application.'

$unauthorizedStatus = 0
try {
    Invoke-WebRequest -Uri "$BaseUrl/audit/logs" -UseBasicParsing | Out-Null
}
catch {
    if ($_.Exception.Response) { $unauthorizedStatus = [int]$_.Exception.Response.StatusCode }
}
Assert-True ($unauthorizedStatus -eq 401) 'Protected endpoint did not reject a missing API key.'

$marker = 'wanwei-smoke-' + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$capsuleBody = @{
    memory_class = 'knowledge'
    content = @{ text = "Cross-platform deployment marker $marker" }
    scene = 'deployment_smoke'
} | ConvertTo-Json -Depth 5
$capsule = Invoke-RestMethod -Uri "$BaseUrl/memory/v2/capsules" -Method Post -Headers $headers -ContentType 'application/json' -Body $capsuleBody
Assert-True ($capsule.capsule_id -like 'cap_*') 'Capsule write did not return a capsule ID.'

$search = Invoke-RestMethod -Uri "$BaseUrl/memory/v2/search?q=$marker&top_k=5" -Method Get -Headers $headers
Assert-True ($search.results.Count -ge 1) 'The newly written capsule was not retrieved.'
Assert-True ($search.results[0].capsule_id -eq $capsule.capsule_id) 'Search returned a different capsule.'

$workflowBody = @{
    scenario = 'weekly_report_preference_learning'
    user_goal = 'Verify the local cross-platform deployment.'
    include_model_gateway = $false
    include_forgetting = $false
    dry_run = $true
} | ConvertTo-Json
$workflow = Invoke-RestMethod -Uri "$BaseUrl/workflow/runs" -Method Post -Headers $headers -ContentType 'application/json' -Body $workflowBody
Assert-True ($workflow.run_id -like 'wfr_*') 'Workflow did not return a run ID.'
Assert-True ($workflow.status -in @('completed', 'completed_with_skips')) 'Workflow did not complete successfully.'

Write-Host "Smoke passed: $($health.version), capsule=$($capsule.capsule_id), workflow=$($workflow.run_id)" -ForegroundColor Green
