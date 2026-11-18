# OZ Report HTTP 연결

1. 연결 종류에서 `OZ Report (HTTP)`를 선택합니다. Host에 HTTP/HTTPS URL을 입력하면 자동으로 선택됩니다.
2. 주소에 `http://222.231.28.46:8080/oz80/server`처럼 전체 서버 URL을 입력합니다. 포트는 URL에서 사용합니다.
3. OZ Repository Manager에서 사용하는 아이디와 비밀번호를 입력하고 Connect를 누릅니다.
4. 서버에서 USL을 사용하는 경우 USL을 선택합니다.

연결 탭별로 별도 Java 프로세스와 OZ API 세션을 사용합니다. 비밀번호는 프로세스 명령줄에 넣지 않고 표준 입력으로 전달합니다.

지원: 폴더 목록과 경로 이동, 파일 다운로드·업로드(기존 파일은 체크인), 파일 복사, 빈 파일/폴더 생성, 파일과 폴더 삭제(모든 하위 항목 포함).
미지원: SSH 명령/터미널, Unix 권한 변경, 이름 변경과 이동. OZ 권한·체크아웃 정책에 따라 서버가 업로드를 거절할 수 있습니다.
진행 중 전송을 취소하면 Java 연결을 종료하므로 다시 연결해야 합니다.

## 실행 환경

OZ Report 8.0 설치가 필요합니다. 기본 검색 위치:

`C:\Program Files (x86)\FORCS\OZ Report 8.0`

다른 위치에 설치했다면 `OZ_REPORT_HOME` 환경 변수를 해당 설치 폴더로 설정합니다.
설치 폴더 아래 Designer의 `lib/ozsfw80.jar`, `lib/log4j.jar` 및 `jre/bin/java.exe`를 이용합니다.
설치된 Java가 없으면 PATH의 Java를 사용합니다. FORCS 라이브러리는 EXE에 재배포하지 않습니다.
서버는 공식 Server API 접속을 허용해야 합니다(`allow_service_api` 및 저장소 접근 권한).

## 연결 모듈 빌드

`oz_bridge/OZRepositoryBridge.java`는 설치된 공식 API의 공개 메서드를 호출합니다.
JDK 21에서 아래와 같이 Java 8 호환 클래스로 빌드합니다(설치 경로에 맞게 조정).

```powershell
javac --release 8 -encoding UTF-8 -classpath "C:\Program Files (x86)\FORCS\OZ Report 8.0\OZ Report Designer 8.0\lib\ozsfw80.jar" -d oz_bridge/classes oz_bridge/OZRepositoryBridge.java
jar cf oz_bridge/oz_repository_bridge.jar -C oz_bridge/classes .
```

EXE 빌드 시 `SFTP_Client.spec`이 연결 모듈 JAR를 포함합니다. 계정 입력과 실제 서버의 인증·전송 검증은 별도로 필요합니다.
