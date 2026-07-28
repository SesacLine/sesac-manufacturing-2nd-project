# KG(Neo4j) 인프라 탑재 검토 — Docker vs Aura vs 별도 EC2 (0728)

> **최종 결정(0728, 갱신): ③안 — AuraDB Free.** 인스턴스 생성 완료.
>
> ~~결정(0728): ④안 — 별도 EC2(t3.small) + Docker Neo4j~~ → **번복**. ④안은 §0·§7의
> "KG 담당자 로컬 그래프의 **덤프**를 받아 옮긴다"는 전제 위에 서 있었는데, **모델 교체로
> KG를 통째로 리빌드하게 되면서 그 전제가 사라졌다.** 덤프 이관의 유일한 이점(현 그래프 보존)이
> 0이 되고, 남는 건 운영 비용뿐이다. 뒤집은 근거 3가지:
>
> 1. **리빌드 반복 비용** — ④는 리빌드마다 `로컬 빌드 → dump → scp → docker load → restart`.
>    ③은 담당자가 로컬 스크립트를 Aura URI로 실행하면 서버에 즉시 반영(핸드오프 0회).
> 2. **빌드 경로가 SG에 막힌다** — ④의 `SG-WAEFER-KG`는 7687을 앱 SG로만 여니 담당자 로컬에서
>    그래프를 쓸 수 없다. 우회안(집 IP 임시 개방 / KG EC2에서 직접 빌드)은 각각 §6이 내세운
>    프라이빗 DB 티어 스토리를 깨거나, t3.small에 `OPENAI_API_KEY`+torch 의존을 얹는다.
> 3. **§7의 SSH 제약과 곱해진다** — 집 공유기/통신사 22번 차단(0728 확인)이라 ④는 리빌드 때마다
>    핫스팟을 물어야 한다. ③은 SSH가 아예 필요 없다(콘솔 + TLS).
>
> ④의 메모리 이점(§2)은 ③도 동일하게 갖는다 — 그건 ①동거안 대비 이점이지 ③ 대비가 아니다.
> 비용도 ④ ~$1 / ③ $0로 사실상 동률이라 판단 근거가 되지 못한다.
>
> **③이 안고 가는 리스크와 대응**: Aura Free는 인스턴스 1개라 스테이징/프로덕션 분리가
> 안 되고, `0_reset.py`가 DB를 비우고 시작하므로 빌드 실패 시 반쯤 망가진 그래프가 라이브가 된다.
> → **리빌드 중에는 서버 `.env`를 `KG_LIVE=0`으로 내려두고, 라벨 카운트 검증 통과 후에만 1로
> 올린다.** §5 폴백 사다리는 그대로 유효하다.
>
> 아래 §1~§6은 결정 당시의 검토 기록으로 남긴다 — **§3·§6의 덤프/Docker 절차는 폐기**되었고,
> 실행 절차는 §4(Aura)가 정본이다.

## 0. 전제

- 현재 데모는 **파일 모드**(`hypotheses.json` 조회)로 완전 동작 — Neo4j는 필수가 아니라
  **④ KG 조회를 라이브 순회(`KG_LIVE=1`)로 시연**하기 위한 아키텍처 보강.
- `KG_LIVE=1` 효과: Neo4j 라이브 순회(LiveKGClient) + 패턴 진입. **의미 진입(KG_SEMANTIC)은
  `kg_rca/outputs/signature_index.json`이 repo에 없어 자동 비활성** — 시연하려면 KG 담당자가
  인덱스 생성 필요.
- ~~어느 방식이든 공통 관문 = 그래프 데이터 적재: KG 담당자 로컬 Neo4j의 덤프
  (`neo4j-admin database dump`) 확보가 선행돼야 한다.~~
  → **폐기(0728).** 모델 교체로 KG를 리빌드하므로 옮길 그래프가 없다. 공통 관문은
  **Aura에 직접 리빌드**(`0_reset` → `4_ingest` → `5_build` → `6_ask` → `7_build_signature_index`)로
  대체됐다. 적재 단계만 떼어내는 건 불가능하다 — 그래프 본체가 `5_build`의 LLM 추출 산출물이다.
- 최우선 기준: **데모 안정성** (발표 중 배치 라이브 실행과 공존해야 함).

## 1. 선택지 비교

| 기준 | ① Docker (EC2 동거) | ② 별도 EC2 | ③ AuraDB Free |
|---|---|---|---|
| 비용 | $0 | +$15~30/월 | $0 |
| 앱 서버 메모리 영향 | 있음 — 아래 실계산 | 없음 | 없음 |
| 설정 시간 | ~1시간 | 2~3시간 | ~30분 |
| 외부 노출/TLS | **없음** — localhost 바인딩, SG 변경 불필요 | SG 관리 필요 | TLS 기본(neo4j+s), 외부 SaaS |
| 관리 | 백업·재시작 직접 | 동일+인스턴스 | 제로(관리형). 장기 미사용 시 일시정지(콘솔 재개) |
| 팀 공유 | EC2 안에서만 | 설정 나름 | 전원 동일 URI 공유 |
| 발표 스토리 | "KG까지 자체 호스팅" 일관성 | 동일 | SaaS — 단 KG는 공개 문헌 지식(기밀 아님)이라 방어 가능, 운영 전환은 URI 교체뿐(VLM과 동일 논리) |
| 용량 제약 | 없음 | 없음 | 노드 20만/관계 40만 (우리 KG 수백 노드 — 무관) |

## 2. ① Docker 동거 메모리 실계산 (t3.medium 4GB)

| 항목 | 상주 예상 |
|---|---|
| OS+systemd+Nginx | ~300MB |
| 백엔드(유휴 실측 386MB) + 배치 피크(torch·MCP) | ~1.0~1.2GB |
| Docker 데몬 | ~150MB |
| Neo4j (상한 적용: heap 512M + pagecache 128M + JVM 오버헤드) | ~1.0~1.1GB |
| **합계 / 여유** | **~2.6~2.8GB / ~1.2GB** |

우리 그래프는 초소형이라 pagecache 128MB로 충분(전체 그래프가 메모리에 적재됨).
Neo4j 공식 권장(2GB+)은 실규모 그래프 기준 — 해당 없음.

**타협 불가 조건 3종** (미이행 시 데모 중 OOM = 최악 실패):
1. 스왑 2GB (OOM 즉사 → 일시 저하로 강등)
2. Neo4j 메모리 상한 명시 (`--memory` + heap/pagecache env)
3. **리허설 게이트**: Neo4j 기동 상태에서 풀 배치 1회 + `free -h` 관찰 —
   여유 500MB 미만으로 떨어지면 불합격 → Aura 전환

## 3. Docker 절차

```bash
# 1) 스왑 (선행 필수)
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 2) Docker
sudo apt-get install -y docker.io && sudo usermod -aG docker ubuntu

# 3) Neo4j — localhost 바인딩(외부 노출 차단, SG 변경 불필요) + 상한
docker run -d --name neo4j --restart unless-stopped \
  -p 127.0.0.1:7474:7474 -p 127.0.0.1:7687:7687 \
  --memory=1200m \
  -e NEO4J_AUTH=neo4j/<비밀번호> \
  -e NEO4J_server_memory_heap_initial__size=512m \
  -e NEO4J_server_memory_heap_max__size=512m \
  -e NEO4J_server_memory_pagecache_size=128m \
  -v ~/neo4j-data:/data \
  neo4j:5

# 4) 데이터 적재 — 담당자 덤프를 scp 후:
docker stop neo4j
docker run --rm -v ~/neo4j-data:/data -v ~/dump:/dump neo4j:5 \
  neo4j-admin database load neo4j --from-path=/dump --overwrite-destination
docker start neo4j
# 검증: MATCH (n) RETURN labels(n)[0], count(*) — 담당자 로컬과 카운트 일치 확인
```

`.env`: `NEO4J_URI=bolt://localhost:7687` + 자격증명 + `KG_LIVE=1` → 서비스 재시작 →
배치 1회 + `free -h` 게이트.

## 4. ③ Aura 절차 (대안/전환용)

1. console.neo4j.io → AuraDB Free 생성(리전 Singapore/Tokyo) — **생성 직후 비밀번호 1회만
   표시, 반드시 저장** + URI(`neo4j+s://xxxx.databases.neo4j.io`) 메모
2. 적재: **Aura URI로 kg_rca 파이프라인 전체를 재실행한다**(덤프 업로드 아님).
   `0_reset` → `4_ingest` → `5_build` → `6_ask` → `7_build_signature_index`.
   "적재만 재실행"은 성립하지 않는다 — 그래프 본체가 `5_build`의 LLM 추출 산출물이다.
   ⚠️ 리빌드 산출물 2종(`outputs/hypotheses.json`·`outputs/signature_index.json`)은 EC2에도
   함께 배포해야 한다. 안 하면 §5 폴백 사다리로 파일 모드에 내려갔을 때 그래프 세대와 어긋나
   다른 결과가 나온다("화면 동작 동일"이라는 폴백 전제가 깨진다).
3. EC2 `.env`: `NEO4J_URI=neo4j+s://...` + 자격증명 + `KG_LIVE=1` → 재시작
4. 발표 전날 콘솔에서 일시정지 여부 확인(쿼리 1회로 재개)

## 5. 폴백 사다리 (데모는 어떤 경우에도 안 죽는 구조)

```
Docker 동거 (리허설 게이트 통과 시)
  └ 불합격 → Aura Free (URI만 교체)
       └ 불안 → .env에서 KG_LIVE 제거 = 즉시 파일 모드 복귀 (화면 동작 동일)
```

## 6. ④안 (채택) — 별도 EC2 + Docker Neo4j

### 비용·타당성

- t3.small(2vCPU/2GB) ~$15/월 + EBS 8GB ~$0.6 → **발표까지 실사용 ~$1**.
  총 인프라 ~$52/월 — 크레딧 $150 대비 여유.
- 타당성: ① 동거안의 리허설 게이트(메모리 감시) 자체가 불필요해짐 — 확실성 구매
  ② 발표 아키텍처에 "앱/지식DB 티어 분리" 성립(SG 참조로 사실상 프라이빗 DB 티어)
  ③ Aura 대비 일시정지 리스크 없음·VPC 내부 통신·전부 자체 호스팅 일관성
  ④ 관리 대상 +1이 유일 비용 — 발표 후 정리에 Terminate 한 줄 추가로 상쇄.

### 인스턴스 스펙 (콘솔 ~30분)

| 항목 | 값 |
|---|---|
| 이름 / AMI / 타입 | `WAEFER-KG` / Ubuntu 24.04 (x86) / **t3.small** |
| 키페어 | 기존 `waefer` 재사용 |
| 네트워크 | `WAEFER-VPC` / `WAEFER-PUBLIC-A` / 퍼블릭 IP **활성화**(Docker 이미지 pull용) |
| 스토리지 | 8GB 기본 |
| 신규 SG `SG-WAEFER-KG` | 인바운드 ① SSH 22(관리) ② **7687 소스 = `SG-WAEFER`(보안그룹 참조)** — "앱 서버에서만 접속" 규칙 하나로 성립, 인터넷엔 미개방 |
| EIP | 불필요 — 앱은 **사설 IP**(10.0.1.x)로 접속, 관리 SSH는 유동 퍼블릭 IP |

### 서버 내 절차

```bash
# Docker 설치
sudo apt-get update && sudo apt-get install -y docker.io && sudo usermod -aG docker ubuntu

# Neo4j — 전용 인스턴스라도 상한은 습관적으로 명시 (2GB 중 1.2GB 캡)
docker run -d --name neo4j --restart unless-stopped \
  -p 7474:7474 -p 7687:7687 \
  --memory=1200m \
  -e NEO4J_AUTH=neo4j/<비밀번호> \
  -e NEO4J_server_memory_heap_initial__size=512m \
  -e NEO4J_server_memory_heap_max__size=512m \
  -e NEO4J_server_memory_pagecache_size=128m \
  -v ~/neo4j-data:/data \
  neo4j:5
# (0.0.0.0 바인딩이어도 SG-WAEFER-KG가 7687을 앱 SG로만 허용 — 외부 차단)

# 덤프 복원 (§3의 4단계와 동일)
docker stop neo4j
docker run --rm -v ~/neo4j-data:/data -v ~/dump:/dump neo4j:5 \
  neo4j-admin database load neo4j --from-path=/dump --overwrite-destination
docker start neo4j
```

### 앱 서버 연결

```
# WAEFER-App의 .env
NEO4J_URI=bolt://<WAEFER-KG 사설IP>:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<비밀번호>
KG_LIVE=1
```

재시작 → 배치 1회로 ④ 라이브 순회 검증. 폴백 사다리(§5)는 그대로:
불안 시 `KG_LIVE` 제거 = 파일 모드 즉시 복귀.

### 발표 후 정리 추가 항목

- [ ] `WAEFER-KG` 인스턴스 Terminate (EIP 없으므로 릴리스 대상 아님)

## 7. 선행 확인 사항

- [x] ~~KG 담당자에게 **덤프 파일** 요청~~ → 폐기(리빌드로 대체, §0)
- [x] Aura 인스턴스 생성 (0728 완료)
- [ ] `.env` 2곳(`루트`·`kg_rca/`)의 `NEO4J_*` 4줄을 Aura 값으로 교체 → `1_test_connection.py` 통과
- [ ] KG 프롬프트 영어화(description·sentence) — **`tier`/`evidence` 센티넬은 제외**.
      `"자동"/"반자동"/"근거없음"`은 `state.py:13`·`hypothesis.py:76,385`·`critic.py:90,156,163`이
      직접 비교하는 제어값이라, 영어로 바꾸면 예외 없이 조용히 오분기한다
      (`schemas.py:20-27`이 영어 키도 받아서 API는 정상처럼 보인다 — 발견이 늦어짐).
- [ ] Aura에 리빌드 → 라벨/관계 카운트 검증 → 그 후에만 `KG_LIVE=1`
- [ ] 리빌드 산출물 EC2 배포 (`hypotheses.json` + `signature_index.json`)
- [ ] 리빌드 후 재확인: `matched_cause` 매칭률 · E2E SC-CENTER-01 · `.env_example`의
      `KG_EXTRACT_MODEL`/`KG_SYNTH_MODEL` 갱신
- [ ] 의미 진입까지 시연할지 결정 → 필요 시 signature_index.json 생성 요청
- [x] ~~서버 작업은 SSH 가능한 네트워크에서~~ → Aura 채택으로 KG쪽 SSH 작업 소멸
      (앱 서버 배포 작업에는 여전히 해당 — 집 공유기/통신사 22번 차단 확인됨(0728))
