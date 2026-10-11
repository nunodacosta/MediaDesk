# Licenciamento — explorar a via OSI + SignPath (assinatura gratuita)

**Objetivo (decisão do autor):** software **livre, com créditos aos autores**,
sem pagar por certificado. A única assinatura gratuita reconhecida pelo Windows
é a da **SignPath Foundation**, que exige licença **aprovada pela OSI**.

> ⚠️ Este documento é uma **análise**, não um parecer jurídico. **Decisão tomada
> (2026-10-11): adotar GPL-3.0**, e o texto foi atualizado em conformidade;
> o autor deve rever a redação final antes da publicação pública.

## 1. Situação atual

- `licenses\ALDACO-IP-NOTICE.txt` (PT/EN, versão portuguesa prevalece) declara
  "todos os direitos reservados", com reutilização condicionada a créditos
  (cláusula 4) e restrições fora disso (cláusula 5).
- Isto **não é** uma licença OSI: não consta da lista do Open Source Initiative,
  tem restrições (ex.: proibição de traduzir/descompilar sem autorização; proibição
  de reprodução substancial das interfaces) que o GPL/MIT não preveem na mesma
  forma.
- Consequências práticas: **não elegível** para a SignPath Foundation; e
  plataformas como GitHub Releases / winget / editores de pacotes preferem
  licenças padrão reconhecidas.

## 2. Opções OSI compatíveis com o objetivo ("livre + créditos")

| Licença | Copyleft | Derivados | Créditos | Notas |
|---|---|---|---|---|
| **GPL-3.0** (recomendada) | Forte | Têm de continuar livres | Obrigatórios (rever §7) | Garante que a obra e derivados permanecem livres; termos adicionais de crédito possíveis (§7) |
| MIT / BSD-3 | Não | Podem vir a ser fechados | Obrigatórios (copyright no derivado) | Mais simples; não garante que derivados fiquem livres |
| Apache-2.0 | Não | Podem vir a ser fechados | Obrigatórios (NOTICE) | Permissiva + concessão de patente; mais texto |
| MPL-2.0 | Ao nível do ficheiro | Híbrido | Obrigatórios | Bom para bibliotecas |

**Recomendação:** **GPL-3.0**. Alinha com "que seja livre": quem reutilizar tem de
manter os créditos e **manter aberto** o que fizer a partir deste código. É também
compatível para redistribuir os componentes já incluídos:

| Componente | Licença | Compatível com GPL-3.0 (redistribuição) |
|---|---|---|
| ffmpeg | GPL (licença GPL-3.0 em `licenses\`) | ✅ |
| yt-dlp | Unlicense (domínio público) | ✅ |
| Deno | MIT | ✅ |
| Python | PSF | ✅ |
| .NET / WebView2 | MIT / proprietária (redistribuível) | ✅ |
| Código próprio | passa a GPL-3.0 | — |

> Nota sobre "kits" GPL vs permissivos: um .exe todo-num-ficheiro com código GPL
> embutido deve acompanhar a oferta do código-fonte (a GPL-3.0 permite indicar
> "no physical medium" até 84 meses). É um ponto a tratar na página de descarga.

## 3. O que muda na prática

1. **`LICENSE`** na raiz com o texto GPL-3.0
   (https://www.gnu.org/licenses/gpl-3.0.txt).
2. **Aviso ALDACO** reescrito por cima: copyright do autor + termos GPL-3.0 +
   termos adicionais de crédito (§7). A cláusula de créditos passa a enquadrar-se
   na GPL (preservação de avisos razoáveis de autor).
3. Interface ("Termos e aviso legal") e `README`/`licenses.json` atualizados.
4. Publicação do **código-fonte num repositório público** (GitHub/GitLab).
5. Candidatura à **SignPath Foundation** com os requisitos de OSS
   (repo público, mantido, lançado, sem malware, MFA, builds verificáveis).
6. Integração do fluxo de assinatura da SignPath no build/CI.

## 4. Proposta de redação do novo aviso (a rever)

> **Em EN, para manter a versão PT prevalecente.**

- PT: "Copyright (c) 2026 Alexandre da Costa / ALDACO. Este programa é software
  livre sob a licença **GPL-3.0** (consulte `LICENSE`). Ao distribuir ou modificar
  este programa, mantenha este aviso e os créditos seguintes: 'Conceito, design e
  direção: Alexandre da Costa / ALDACO. Implementação técnica assistida por
  inteligência artificial, sob direção do autor.'" *(+ termos adicionais §7:
  preservação dos créditos e proibição de sugerir endosso/autorização do autor.)*
- EN: "Copyright (c) 2026 Alexandre da Costa / ALDACO. This program is free
  software under the **GPL-3.0** license (see `LICENSE`). When distributing or
  modifying this program, keep this notice and the following credits: ..."

> ⚠️ A redação final (nomeadamente o uso correto dos termos adicionais da
> GPL-3.0, §7) deve ser revista por ti — e, se quiseres, submetida à SignPath
> antes da candidatura.

## 5. Decisão (2026-10-11)

- [x] **Adotar GPL-3.0** (recomendada).
- [x] Aviso ALDACO reescrito (PT/EN) como "aviso de licença e créditos", com
      termo adicional de créditos (GPL-3.0 §7).
- [x] `LICENSE` (texto integral GPL-3.0) na raiz do projeto.
- [x] Interface ("Termos e aviso legal") e `licenses/ALDACO-IP-NOTICE.txt`
      atualizados; README atualizado.
- [ ] **Publicar o código-fonte num repositório público** (GitHub/GitLab) —
      requisito da SignPath Foundation.
- [ ] **Candidatar-se à SignPath Foundation** e integrar o fluxo de assinatura.

> Antes de publicar, rever o texto final do aviso (`licenses/ALDACO-IP-NOTICE.txt`
> e o bloco `LEGAL_NOTICE` em `index.html` — versão PT prevalece) e confirmar a
> disponibilização do código-fonte (a GPL-3.0 exige oferta do fonte aos
> utilizadores dos binários).