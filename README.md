# ebook-risk-analyzer

EPUB 및 HTML 전자책에서 사람이 검토할 만한 **위험 신호**를 찾아 로컬 파일로 정리하는 오프라인 우선 도구입니다. 이 도구의 결과는 저자, 편집자, 출판 담당자의 검토 순서를 돕기 위한 것이며, 저작물의 작성 방식·진위·품질을 진단하거나 판정하지 않습니다. 각 finding에는 위치, 발췌문, 신호의 이유, 권장 검토 조치가 포함됩니다.

## 지원 범위와 개인정보

- 지원 입력: `.epub`, 단일 HTML/XHTML/XML/TXT 파일, 또는 이 파일들이 든 디렉터리. Windows에서는 `.\book.txt`, POSIX에서는 `./book.txt`처럼 TXT 파일을 직접 지정할 수 있습니다.
- 기본 동작은 네트워크 요청을 하지 않습니다. `--verify-links`를 지정한 경우에만 외부 링크 확인을 시도할 수 있으므로, 폐쇄망에서는 지정하지 마십시오.
- 입력 원고와 결과물은 사용자가 지정한 로컬 경로에만 남습니다. 민감한 원고는 조직의 보관·접근 정책에 맞는 로컬 드라이브에서 처리하십시오.
- 저작권 있는 원고는 분석 권한을 가진 경우에만 사용하십시오. 결과의 `excerpt`에도 원문 일부가 들어갈 수 있으므로 결과 파일을 원고와 같은 수준으로 보호하십시오.
- Windows 설치형 및 휴대용 실행 파일은 Python이나 외부 AI API 없이 동작하며, 한국어 로컬 웹 화면과 명령줄을 함께 제공합니다.

## Windows 빠른 설치 (비개발자 권장)

Python은 설치하지 않아도 됩니다. GitHub Actions가 64비트 Windows 10/11용 설치 파일과 휴대용 ZIP을 자동으로 빌드합니다.

1. 저장소의 [Actions → Build Windows Installer](https://github.com/eowlsdh/ebook-risk-analyzer/actions/workflows/windows-build.yml)에서 초록색으로 성공한 최신 실행을 엽니다.
2. 화면 아래 **Artifacts**에서 다음 중 하나를 내려받습니다. GitHub 로그인이 필요할 수 있습니다.
   - `EbookRiskAnalyzer-Setup-x64`: 일반 사용자 권장 설치형
   - `EbookRiskAnalyzer-Portable-x64`: 설치 권한이 없을 때 사용하는 휴대용
3. GitHub에서 받은 Artifact ZIP을 먼저 압축 해제합니다.
4. 설치형은 `EbookRiskAnalyzer-Setup-x64.exe`를 실행합니다. 휴대용은 ZIP을 완전히 푼 뒤 `EbookRiskAnalyzer.exe`를 실행합니다.
5. 자동으로 열린 한국어 웹 화면에서 EPUB/HTML/XHTML/TXT 파일 또는 HTML 원고 폴더를 선택하고 **로컬 분석 시작**을 누릅니다.

휴대용 버전은 `_internal` 폴더를 포함한 압축 해제 폴더 전체가 필요합니다. EXE만 따로 복사하면 실행되지 않습니다. 현재 배포 파일에는 상용 코드 서명이 없으므로 Windows SmartScreen이 경고할 수 있습니다. 파일을 이 공식 저장소의 성공한 빌드에서 받았는지 확인한 후 **추가 정보 → 실행**을 선택하십시오.

프로그램은 `127.0.0.1`에만 연결되는 로컬 웹 화면을 사용합니다. 기본 분석은 원고를 외부 서버나 LLM에 보내지 않습니다. **외부 링크도 확인하기**를 직접 켠 경우에만 URL/DOI 상태 확인을 위한 네트워크 요청이 발생합니다.

### 소스에서 설치하는 방법

개발자 또는 macOS/Linux 사용자는 Python 3.11 이상에서 다음과 같이 설치할 수 있습니다.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
```

## macOS/Linux 설치

```sh
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

설치 뒤에는 어느 운영체제에서나 다음 둘 중 하나로 실행합니다.

```sh
ebook-risk-analyzer --help
python -m ebook_risk_analyzer --help
```

## 폐쇄망(오프라인) 설치와 운영

인터넷에 연결된, 대상 Windows와 같은 Python 버전·아키텍처의 준비 컴퓨터에서 wheelhouse를 만듭니다. 이 프로젝트 폴더에서 실행합니다.

```powershell
py -3.11 -m pip wheel --wheel-dir wheelhouse .
```

`wheelhouse` 폴더와 프로젝트 전체를 폐쇄망 컴퓨터로 복사합니다. 폐쇄망 컴퓨터에서는 활성화된 가상 환경에서 인덱스를 전혀 조회하지 않도록 설치합니다.

```powershell
python -m pip install --no-index --find-links .\wheelhouse .
```

POSIX에서는 경로 구분자만 바꿉니다.

```sh
python -m pip install --no-index --find-links ./wheelhouse .
```

일상 분석에는 `--verify-links`를 생략하십시오. 링크 검증이 필요할 때만 승인된 네트워크 환경에서 명시적으로 추가합니다. 결과를 다른 시스템으로 옮길 때는 `report.json`, `report.html`, `findings.csv`, `extracted_text.txt`, `metadata.json`에 원문 조각과 메타데이터가 있을 수 있음을 확인하십시오.

## 분석 실행

Windows PowerShell 예시:

```powershell
ebook-risk-analyzer analyze .\examples\sample_book --output .\out\sample --language auto --format all
```

Windows cmd.exe에서도 같은 명령을 쓰되 `\` 경로를 사용합니다. POSIX 예시는 다음과 같습니다.

```sh
ebook-risk-analyzer analyze ./examples/sample_book --output ./out/sample --language auto --format all
```

`analyze SOURCE --output DIR`의 주요 옵션:

| 옵션 | 설명 |
| --- | --- |
| `--language auto\|ko\|en` | 언어 자동 감지 또는 한국어/영어 규칙 선택 |
| `--format json\|html\|all` | 주 보고서 형식 선택. `all`은 두 형식을 작성 |
| `--config PATH` | 기본 규칙 대신 또는 함께 사용할 YAML 규칙 설정 |
| `--max-file-size BYTES` | 입력 파일의 최대 바이트 수. 한도를 넘는 파일 또는 디렉터리는 즉시 오류로 종료 |
| `--verify-links` | 링크 확인을 요청. 기본값은 꺼짐이며 네트워크를 사용할 수 있음 |
| `--verbose` | 처리한 파일 정보를 더 자세히 표시 |
| `--fail-on high\|critical\|never` | 해당 심각도 이상이 있으면 종료 상태를 실패로 설정. 검토 자동 판정은 하지 않음 |

두 판본의 신호 변화를 비교하려면 다음을 실행합니다.

```powershell
ebook-risk-analyzer compare .\drafts\edition-1.epub .\drafts\edition-2.epub --output .\out\comparison --language ko --format all
```

```sh
ebook-risk-analyzer compare ./drafts/edition-1.epub ./drafts/edition-2.epub --output ./out/comparison --language ko --format all
```

자동화에서는 `--fail-on never`를 기본으로 두고 사람이 결과를 검토하는 것이 안전합니다. CI에서 검토 대기 항목을 표시해야 할 때만 조직의 검토 절차에 맞는 수준을 명시하십시오.

## 결과 읽기와 검토 절차

출력 폴더에는 다음 파일이 생성됩니다.

- `report.json`: 기계 처리용 주 보고서. 최상위 키는 `book`, `summary`, `category_scores`, `findings`입니다.
- `report.html`: 사람이 읽기 쉬운 주 보고서입니다.
- `findings.csv`: 스프레드시트 필터링용 finding 목록입니다.
- `extracted_text.txt`: 분석에 사용한 추출 텍스트입니다.
- `metadata.json`: 입력의 제목, 작성자, 언어 등 읽을 수 있었던 메타데이터입니다.

각 finding의 `source location`으로 원본을 열고, `excerpt` 전후 문맥을 읽으십시오. 이어서 `reason`이 실제 편집 이슈에 적용되는지 판단하고, `review action`을 편집 작업으로 전환하십시오. 점수와 severity는 검토 우선순위 신호일 뿐 오류의 확률, 저작자 특성, 저작물의 작성 주체를 나타내지 않습니다. 반복 표현, 인용 형식, 번역체, 의도적인 문체, 장르 관습은 흔한 오탐 원인입니다. 오탐은 원고를 고치기보다 finding을 검토 기록에서 종결하고, 반복되면 설정을 조정하십시오.

## 규칙 설정과 백업

기본 규칙은 `config/default_rules.yaml`에 있습니다. 직접 수정하지 말고 사본을 만들어 프로젝트 또는 출판사별 설정으로 관리하십시오.

```powershell
Copy-Item .\config\default_rules.yaml .\config\publisher-rules.yaml
ebook-risk-analyzer analyze .\book.epub --output .\out\book --config .\config\publisher-rules.yaml --format all
```

```sh
cp ./config/default_rules.yaml ./config/publisher-rules.yaml
ebook-risk-analyzer analyze ./book.epub --output ./out/book --config ./config/publisher-rules.yaml --format all
```

설정 변경 전에는 원본 YAML과 대표 결과 폴더를 날짜가 포함된 별도 위치에 복사합니다. 변경 후에는 동일한 샘플 원고로 전후 `findings.csv`를 비교하고, 변경 이유·승인자·도구 버전을 기록하십시오. 분석 전에는 원고의 읽기 전용 백업을 만들고, 분석 출력은 원고 폴더와 분리하여 보관하십시오.

업데이트는 새 릴리스의 `pyproject.toml`과 잠금/배포 정책을 확인한 뒤, 별도 가상 환경에서 먼저 검증합니다. 폐쇄망은 승인된 wheelhouse를 새로 만들고 이전 wheelhouse와 결과 기준본을 보관합니다. 운영 가상 환경을 덮어쓰지 말고, 대표 EPUB·HTML로 결과 차이를 검토한 후 전환합니다.

## 처음 사용하는 사람을 위한 10분 실행 순서

아래 순서는 Windows PowerShell 기준입니다. 명령마다 오류가 없다면 다음 단계로 이동합니다.

1. 프로그램 폴더를 `C:\ebook-risk-analyzer`처럼 짧고 알아보기 쉬운 위치에 복사합니다.
2. 분석할 책은 프로그램 폴더 밖의 `C:\Books`에, 결과는 `C:\Reports`에 두는 것을 권장합니다.
3. PowerShell을 열고 프로그램 폴더로 이동합니다.

```powershell
cd C:\ebook-risk-analyzer
```

4. 가상 환경을 만들고 프로그램을 설치합니다.

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install .
```

5. 설치 상태를 확인합니다.

```powershell
python -m ebook_risk_analyzer --help
```

6. 제공 예제로 먼저 시험합니다.

```powershell
python -m ebook_risk_analyzer analyze .\examples\sample_book --output C:\Reports\sample-check --fail-on never
```

7. `C:\Reports\sample-check\report.html`을 더블클릭합니다. 브라우저에서 제목, 위험 점수, 카테고리 점수, 발견 표와 필터가 보이면 설치가 완료된 것입니다.
8. 실제 EPUB을 분석합니다.

```powershell
python -m ebook_risk_analyzer analyze "C:\Books\검토할 책.epub" --output "C:\Reports\검토할 책" --language auto --fail-on never
```

명령을 실행할 때마다 먼저 `.\.venv\Scripts\Activate.ps1`로 가상 환경을 활성화하십시오. 프롬프트 앞에 `(.venv)`가 표시되면 활성 상태입니다.

## 입력 유형별 복사 가능한 명령

```powershell
# EPUB 한 권
python -m ebook_risk_analyzer analyze "C:\Books\book.epub" --output "C:\Reports\book"

# HTML/XHTML 한 파일
python -m ebook_risk_analyzer analyze "C:\Books\chapter01.xhtml" --output "C:\Reports\chapter01"

# 여러 HTML/XHTML/TXT가 있는 폴더
python -m ebook_risk_analyzer analyze "C:\Books\html-book" --output "C:\Reports\html-book"

# 일반 텍스트 원고
python -m ebook_risk_analyzer analyze "C:\Books\manuscript.txt" --output "C:\Reports\manuscript"

# 한국어 규칙을 명시
python -m ebook_risk_analyzer analyze "C:\Books\book.epub" --output "C:\Reports\book-ko" --language ko

# 영어 규칙을 명시
python -m ebook_risk_analyzer analyze "C:\Books\book.epub" --output "C:\Reports\book-en" --language en

# 최대 파일 크기를 100 MiB로 지정
python -m ebook_risk_analyzer analyze "C:\Books\book.epub" --output "C:\Reports\book" --max-file-size 104857600
```

경로에 공백·한글·괄호가 있으면 항상 큰따옴표로 감싸십시오. 원본 EPUB은 읽기만 하며 수정하지 않습니다. 기존 출력 폴더를 다시 사용하면 같은 이름의 보고서가 갱신되므로 이전 결과가 필요하면 먼저 폴더를 백업하십시오.

## 일상적인 검수 절차

1. 원본을 읽기 전용 위치에 백업합니다.
2. 책마다 별도 출력 폴더를 지정하여 `--fail-on never`로 분석합니다.
3. `report.html`을 열고 높은 심각도와 점수가 높은 카테고리부터 확인합니다.
4. finding의 파일·장·문단·문장 위치를 원본에서 찾아 발췌문 전후 문맥을 읽습니다.
5. `reason`은 탐지 규칙의 설명이며 사실 판정이 아닙니다. `review_action`을 참고하여 수정, 유지, 조사 필요 중 하나로 기록합니다.
6. 인용·숫자·고유명사 신호는 원자료와 제작 이력을 별도로 확인합니다.
7. 오탐이 반복되면 원고를 억지로 고치지 말고 프로젝트별 YAML 설정을 조정합니다.
8. 수정판을 다시 분석하고 필요하면 `compare`로 이전 판본과 비교합니다.
9. 보고서에는 원문 발췌와 메타데이터가 들어가므로 원고와 동일한 접근 권한·보존 기간을 적용합니다.

## 설정 파일 안전하게 수정하기

기본 파일을 직접 바꾸지 말고 복사본을 사용합니다.

```powershell
Copy-Item .\config\default_rules.yaml C:\Books\publisher-rules.yaml
notepad C:\Books\publisher-rules.yaml
python -m ebook_risk_analyzer analyze "C:\Books\book.epub" --output "C:\Reports\book-custom" --config "C:\Books\publisher-rules.yaml"
```

설정 키 이름, 값 형식 또는 허용 범위가 잘못되면 분석을 시작하기 전에 오류로 종료됩니다. 한 번에 한 항목만 바꾸고 동일한 예제에서 기본 결과와 사용자 설정 결과를 비교하십시오. 설정 파일에 API 키, 계정, 내부 URL 또는 개인정보를 넣지 마십시오.

## 종료 코드와 자동화

- `--fail-on never`: finding이 있어도 정상 종료합니다. 일반 사용자의 권장값입니다.
- `--fail-on high`: high 이상 finding 또는 60점 이상이면 비정상 종료 상태를 반환합니다.
- `--fail-on critical`: critical finding 또는 80점 이상이면 비정상 종료 상태를 반환합니다.

비정상 종료는 “AI 작성 확정”이나 “책이 잘못됨”을 의미하지 않습니다. 배치 작업에서 사람 검토가 필요한 결과를 표시하기 위한 상태값입니다.

## 업데이트, 제거, 복구

업데이트 전에는 현재 가상 환경과 대표 보고서를 보존하고 새 가상 환경에서 시험하십시오.

```powershell
Deactivate
Rename-Item .venv .venv-backup
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
python -m pytest -q
```

문제가 있으면 새 `.venv`를 삭제하고 `.venv-backup`을 `.venv`로 되돌립니다. 프로그램 제거는 원고·보고서를 백업한 뒤 가상 환경과 프로그램 폴더를 삭제하면 됩니다. 프로그램은 Windows 레지스트리나 원본 전자책을 수정하지 않습니다.

## GitHub 공개 전 개인정보·저작권 점검

이 저장소의 `.gitignore`는 다음을 기본 제외합니다.

- `.gjc/`: 세션 ID, 로컬 사용자 경로와 실행 기록
- `.venv/`, `.wheeltest/`, `build/`, `dist/`, `*.egg-info/`: 로컬 환경과 빌드 결과
- `reports/`, `out/`, `artifacts/`: 원문 발췌·메타데이터가 포함될 수 있는 분석 결과
- `books/`, `manuscripts/`, `*.epub`: 비공개 원고와 전자책
- `.env*`, 인증서·개인키, 로컬 설정 파일

공개하기 전에 반드시 다음을 실행합니다.

```powershell
git status --short
git diff --cached
```

`git status`에 `.gjc`, 가상 환경, 실제 EPUB, 고객 원고, 보고서, 사내 설정이 보이면 커밋하지 마십시오. 이미 `git add`한 파일은 삭제하지 않고 스테이징에서만 제거할 수 있습니다.

```powershell
git restore --staged "파일경로"
```

커밋 전에 이름·이메일·전화번호·주소·사내 URL·계정 ID·API 키·토큰·절대 경로가 없는지 확인하십시오. `examples/sample_book`에는 공개 가능한 합성 예제만 두고 실제 고객 자료를 예제로 사용하지 마십시오. `.gitignore`는 이미 Git이 추적하는 파일을 자동으로 제거하지 않으므로 기존 추적 파일은 별도로 점검해야 합니다.
## 문제 해결

- **`py` 또는 `python`을 찾을 수 없음**: Python 설치 후 새 터미널을 열고 `py -3.11 --version`을 확인합니다. Windows 설치 시 PATH 선택을 놓쳤다면 Python Installer의 Modify에서 PATH를 추가합니다.
- **PowerShell 실행 정책 오류**: 위의 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`는 현재 창에만 적용됩니다.
- **`ebook-risk-analyzer`를 찾을 수 없음**: 가상 환경을 활성화하고 `python -m ebook_risk_analyzer --help`로 실행합니다. 그 뒤 `python -m pip install .`을 다시 실행합니다.
- **오프라인 설치가 외부 서버를 찾음**: `--no-index --find-links`가 모두 포함되었는지, wheelhouse에 Python/Windows에 맞는 `beautifulsoup4`, `lxml`, `PyYAML` wheel이 있는지 확인합니다.
- **입력 파일이 너무 큼**: 도구는 큰 입력을 건너뛰지 않고 즉시 오류로 종료합니다. `--max-file-size` 값을 바이트 단위로 늘리거나 입력을 분할한 뒤 다시 실행합니다. 손상 EPUB은 원본 사본에서 다시 내보냅니다.
- **글자가 깨짐 또는 finding 위치가 예상과 다름**: 원본 HTML 인코딩, EPUB 매니페스트, 장 제목을 확인합니다. `extracted_text.txt`와 원본을 나란히 비교합니다.
- **링크 확인이 실패함**: 폐쇄망에서는 정상일 수 있습니다. 기본값처럼 `--verify-links` 없이 분석하거나 승인된 네트워크에서만 재시도합니다.

## 유지보수와 릴리스 체크리스트

개발 환경에서 의존성을 포함해 설치하고 테스트합니다.

```powershell
py -3.11 -m pip install -e ".[dev]"
py -3.11 -m pytest
```

```sh
python3.11 -m pip install -e '.[dev]'
python3.11 -m pytest
```

릴리스 전 담당자는 다음을 확인합니다.

1. 지원 Python 버전에서 깨끗한 가상 환경 설치와 `--help`를 확인합니다.
2. 제공 샘플의 HTML 디렉터리와 대표 EPUB으로 `analyze`, 서로 다른 두 입력으로 `compare`를 실행합니다.
3. 기본 네트워크 미사용과 `--verify-links`의 명시적 동작을 확인합니다.
4. `report.json`의 최상위 키, HTML/CSV/추출 텍스트/메타데이터 파일 생성, `--format`과 `--fail-on` 경로를 확인합니다.
5. `high`, `critical`, `never` 종료 상태와 큰 파일·손상 입력·비ASCII 텍스트를 점검합니다.
6. 규칙 변경의 전후 결과, 알려진 오탐, 개인정보·저작권 영향, 업그레이드/롤백 절차를 검토 기록에 남깁니다.
7. 배포 전 wheelhouse를 대상 Windows 아키텍처와 Python 버전에서 오프라인 설치해 봅니다.
## Windows 로컬 앱 사용법

자동 빌드가 설치 파일과 휴대용 ZIP을 제공합니다. 다운로드 절차는 위의 **Windows 빠른 설치**를 따르십시오.

- 설치형은 `EbookRiskAnalyzer-Setup-x64.exe`를 실행해 설치합니다. 제거는 Windows **설치된 앱**에서 합니다.
- 휴대용 배포물은 게시자가 제공한 폴더 **전체**를 `C:\Apps\EbookRiskAnalyzer`처럼 쓰기 가능한 로컬 위치에 복사한 뒤 폴더 안의 실행 파일을 실행합니다. 실행 파일 하나만 따로 옮기지 마십시오.
- 첫 실행은 브라우저에 `http://127.0.0.1:포트/`를 엽니다. 이 주소는 현재 PC 안에서만 열립니다. 방화벽에서 공용/개인 네트워크 접근 허용을 묻는 경우 허용하지 말고 취소하십시오.
 
화면에서 EPUB 또는 HTML/HTM/XHTML/TXT 파일을 끌어 놓거나 **파일 선택**을 누르십시오. 여러 HTML/TXT 원고는 **폴더 선택**으로 올릴 수 있고 EPUB은 단독으로 올립니다. 언어를 고른 뒤 **로컬 분석 시작**을 누릅니다. 링크 확인은 기본으로 꺼져 있습니다. 승인된 네트워크에서 꼭 필요할 때만 **외부 링크도 확인하기**를 켜십시오.
 
완료 화면에서 사람이 원문과 제작 이력을 확인한 뒤 다음 다섯 결과를 각각 내려받습니다: `report.json`, `report.html`, `findings.csv`, `extracted_text.txt`, `metadata.json`. 결과에는 원문 발췌와 메타데이터가 들어갈 수 있으므로 원고와 같은 보안 수준으로 보관하고, 필요 없어진 내려받은 보고서는 조직의 보존 정책에 따라 삭제하십시오. 이 도구는 AI 작성 여부, 저작권, 품질을 진단하거나 판정하지 않습니다.
 
폐쇄망에는 인터넷이 연결된 준비 PC에서 검증한 설치형 또는 휴대용 **빌드 산출물 전체**를 승인된 매체로 복사합니다. 링크 확인을 켜지 않으면 기본 분석은 네트워크를 사용하지 않습니다. 바이너리 대신 소스만 배포해야 할 때는 위의 `wheelhouse` 생성 및 `--no-index --find-links` 설치 절차를 사용합니다.
 
문제가 생기면 앱이 연 `127.0.0.1` 주소를 같은 PC 브라우저에 붙여 넣고, 다른 PC에서 접속하려 하지 마십시오. 파일이 거부되면 허용 확장자·파일 크기와 상대 경로를 확인하십시오. `..`가 포함된 경로, 바로가기, 심볼릭 링크는 사용할 수 없습니다. 업데이트는 앱을 종료한 뒤 새 설치 파일을 실행하거나 휴대용 폴더 전체를 교체합니다. 휴대용 제거는 앱 종료 후 그 폴더를 삭제하고, 설치형 제거는 Windows **설치된 앱**에서 수행합니다. 원고와 내려받은 보고서는 별도 위치이므로 필요하면 따로 정리하십시오.
 
게시자는 릴리스마다 깨끗한 Windows 환경에서 설치형·휴대용을 각각 확인하고, 127.0.0.1 전용 바인딩, 기본 네트워크 미사용, 파일/폴더 업로드, 거부 입력, 다섯 결과 다운로드, 업그레이드와 제거를 검증하십시오. 실제 산출물의 파일명·버전·서명·해시를 릴리스 노트에 기록하고, 바이너리가 소스 저장소에 이미 포함된 것처럼 안내하지 마십시오.
