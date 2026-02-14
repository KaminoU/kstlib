  # ══════════════════════════════════════════════════════════
  # JWT Signature Verification - PowerShell (raw RSA math)
  # ══════════════════════════════════════════════════════════

  # --- Config ---
  $jwt = (kstlib auth token)

  # --- Helpers ---
  function Decode-Base64Url([string]$s) {
      $s = $s.Replace('-','+').Replace('_','/')
      switch ($s.Length % 4) { 2 { $s += "==" } 3 { $s += "=" } }
      [Convert]::FromBase64String($s)
  }

  function Bytes-ToHex([byte[]]$b) {
      ($b | ForEach-Object { $_.ToString("x2") }) -join ""
  }

  function Bytes-ToBigInt([byte[]]$bytes) {
      $le = [byte[]]::new($bytes.Length + 1)
      [Array]::Copy($bytes, $le, $bytes.Length)
      [Array]::Reverse($le, 0, $bytes.Length)
      [System.Numerics.BigInteger]::new($le)
  }

  # --- Step 1: Decode JWT ---
  $parts = $jwt.Split(".")
  $headerJson  = [System.Text.Encoding]::UTF8.GetString((Decode-Base64Url $parts[0]))
  $payloadJson = [System.Text.Encoding]::UTF8.GetString((Decode-Base64Url $parts[1]))
  $header  = $headerJson  | ConvertFrom-Json
  $payload = $payloadJson | ConvertFrom-Json

  Write-Host "`n=== JWT Header ===" -ForegroundColor Cyan
  Write-Host $headerJson
  Write-Host "`n=== Claims (issuer, kid) ===" -ForegroundColor Cyan
  Write-Host "  alg = $($header.alg)"
  Write-Host "  kid = $($header.kid)"
  Write-Host "  iss = $($payload.iss)"

  # --- Step 2: Fetch public key ---
  $disco = Invoke-RestMethod "$($payload.iss.TrimEnd('/'))/.well-known/openid-configuration"
  $jwks  = Invoke-RestMethod $disco.jwks_uri
  $key   = $jwks.keys | Where-Object { $_.kid -eq $header.kid }

  Write-Host "`n=== Public Key ===" -ForegroundColor Cyan
  Write-Host "  kid = $($key.kid)"
  Write-Host "  kty = $($key.kty)"

  $modulus   = Decode-Base64Url $key.n
  $exponent  = Decode-Base64Url $key.e
  Write-Host "  size = $($modulus.Length * 8)-bit"

  # --- Step 3: Compute hash ---
  $signedData = [System.Text.Encoding]::ASCII.GetBytes("$($parts[0]).$($parts[1])")
  $alg = $header.alg

  $sha = switch ($alg) {
      "RS256" { [System.Security.Cryptography.SHA256]::Create() }
      "RS384" { [System.Security.Cryptography.SHA384]::Create() }
      "RS512" { [System.Security.Cryptography.SHA512]::Create() }
  }
  $computedHash = $sha.ComputeHash($signedData)

  # --- Step 4: Recover hash from signature (raw RSA) ---
  $signature = Decode-Base64Url $parts[2]

  $sigInt = Bytes-ToBigInt $signature
  $nInt   = Bytes-ToBigInt $modulus
  $eInt   = Bytes-ToBigInt $exponent

  # signature^e mod n = PKCS1 padded block containing hash
  $decrypted = [System.Numerics.BigInteger]::ModPow($sigInt, $eInt, $nInt)
  $decBytes  = $decrypted.ToByteArray()
  [Array]::Reverse($decBytes)

  # Extract hash (last N bytes of PKCS#1 block)
  $hashSize = switch ($alg) { "RS256" { 32 } "RS384" { 48 } "RS512" { 64 } }
  $recoveredHash = $decBytes[($decBytes.Length - $hashSize)..($decBytes.Length - 1)]

  # --- Step 5: PRINT & COMPARE ---
  $computedHex  = Bytes-ToHex $computedHash
  $recoveredHex = Bytes-ToHex $recoveredHash

  Write-Host "`n=== Signature Verification ===" -ForegroundColor Cyan
  Write-Host "  Algorithm: $alg`n"
  Write-Host "  Computed hash  (SHA on header.payload):" -ForegroundColor Yellow
  Write-Host "    $computedHex"
  Write-Host ""
  Write-Host "  Recovered hash (DECRYPT(public_key, signature)):" -ForegroundColor Yellow
  Write-Host "    $recoveredHex"
  Write-Host ""

  if ($computedHex -eq $recoveredHex) {
      Write-Host "  >>> MATCH - The IDP signed this token. Mathematical fact. <<<" -ForegroundColor Green
  } else {
      Write-Host "  >>> MISMATCH - Signature invalid. <<<" -ForegroundColor Red
  }