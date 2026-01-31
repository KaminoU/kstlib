# Binary Dependencies

External tools required by kstlib features.

## SOPS

Secrets encryption/decryption engine.

::::{tab-set}

:::{tab-item} Linux
See [SOPS releases](https://github.com/getsops/sops/releases) for your distro/architecture.
:::

:::{tab-item} macOS (Homebrew)

```bash
brew install sops
```

:::

:::{tab-item} Windows (Scoop)

```powershell
scoop install sops
```

:::

::::

**Verify:**

```bash
sops --version
```

## age

Modern encryption tool (simpler alternative to GPG).

::::{tab-set}

:::{tab-item} Linux
See [age releases](https://github.com/FiloSottile/age/releases) for your distro/architecture.
:::

:::{tab-item} macOS (Homebrew)

```bash
brew install age
```

:::

:::{tab-item} Windows (Scoop)

```powershell
# age is in the extras bucket
scoop bucket add extras
scoop install age
```

:::

::::

**Verify:**

```bash
age --version
age-keygen --version
```

## Quick Check

Run the kstlib doctor command to verify all dependencies:

```bash
kstlib secrets doctor
```
