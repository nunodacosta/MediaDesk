# winget (Windows Package Manager)

Manifestos do pacote **`ALDACO.YTDLPMediaDesk`**, prontos a copiar para o
repositório [`microsoft/winget-pkgs`](https://github.com/microsoft/winget-pkgs).

Instalação (depois de o pacote ser aceite):

```powershell
winget install --id ALDACO.YTDLPMediaDesk -e
```

## Estrutura

A árvore espelha o repositório oficial, para que o PR seja uma cópia direta:

```
winget/manifests/a/ALDACO/YTDLPMediaDesk/<versao>/
  ALDACO.YTDLPMediaDesk.yaml                  # ManifestType: version
  ALDACO.YTDLPMediaDesk.installer.yaml        # ManifestType: installer
  ALDACO.YTDLPMediaDesk.locale.en-US.yaml     # ManifestType: defaultLocale
```

> O locale **predefinido** usa `ManifestType: defaultLocale` (não `locale`).
> `locale` só se aplica a locales adicionais; usar `locale` no en-US faz o
> `winget validate` falhar com “multi file manifest is incomplete”.

## Gerar os manifestos

`tools/gen_winget.ps1` lê `version.json` (versão e data) e o SHA-256 do
`Media.Desk.Setup.exe` (de `dist\SHA256SUMS.txt` ou do parâmetro `-Sha256`):

```powershell
powershell -ExecutionPolicy Bypass -File tools\gen_winget.ps1
# ou, com o hash explícito:
powershell -ExecutionPolicy Bypass -File tools\gen_winget.ps1 -Sha256 <hex>
```

Validação local:

```powershell
winget validate --manifest winget\manifests\a\ALDACO\YTDLPMediaDesk\<versao>
```

## Submeter

```powershell
wingetcreate submit --prtitle "New package: ALDACO.YTDLPMediaDesk version <versao>" `
    winget\manifests\a\ALDACO\YTDLPMediaDesk\<versao>
```

O `wingetcreate` abre o PR em `microsoft/winget-pkgs` a partir de um fork. Na
primeira contribuição é preciso assinar o **Microsoft CLA** (o bot comenta no PR
com as instruções). Depois disso correm os checks automáticos (validação dos
manifestos, URLs, scan do instalador e instalação numa VM).

## Identidade do pacote (não mudar)

| Campo | Valor |
| --- | --- |
| `PackageIdentifier` | `ALDACO.YTDLPMediaDesk` |
| `Publisher` | `ALDACO` |
| `InstallerType` | `inno` |
| `Scope` | `user` |
| `Moniker` | `mediadesk` |
| `License` | `GPL-3.0-or-later` |
| `ProductCode` | `{B7F3E2A1-9C4D-4E7B-8A2F-5D1C6E9B0A34}_is1` |

O `ProductCode` corresponde ao `AppId` do Inno Setup em `installer/mediadesk.iss`
acrescido de `_is1`; é o que liga o pacote à entrada de
«Aplicações e funcionalidades» já instalada.
