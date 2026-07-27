# WAEFER VLM 온프레미스 서빙 — 독자 모델 이미지 패키징

데모는 OpenAI API(pty 트랙)로 VLM 관측을 수행하지만, 실제 팹 환경에서는 웨이퍼맵을
외부 API로 전송할 수 없다(공정 기밀·데이터 주권·폐쇄망). 이 폴더는 **사내 독자 모델
(파인튜닝 가정, 현재는 Qwen3-VL-8B-Instruct)을 가중치까지 포함해 이미지로 패키징**한
서빙 산출물이다.

## 구성 요소

| 파일 | 역할 |
|---|---|
| `Dockerfile` | vLLM 공식 이미지 + 가중치 bake → `waefer-vlm:0.1` |
| `docker-compose.yml` | GPU 호스트 기동 구성 (포트 8001, OpenAI 호환 API) |
| `models/waefer-vlm/` | Qwen3-VL-8B 가중치 (~17GB, `hf download`로 준비) |

## 왜 "코드 수정 0줄" 전환이 가능한가 — PR #99로 원격 분기까지 구현 완료

전환 지점이 코드에 이미 있다 (`wafer_reading/vlm/`):

| 계층 | 구현 | 근거 |
|---|---|---|
| 트랙 분기 | pty(OpenAI API, 기본) / open(오픈웨이트) | `adapter.VLMReader` |
| **open 원격 모드** | `VLM_OPEN_BASE_URL` 설정 시 OpenAI 호환 서버 호출 — **GPU 없는 앱 서버도 open 트랙 사용 가능** | `adapter._open_backend` (PR #99) |
| open 로컬 모드 | in-process 로드, `local_files_only=True`(런타임 다운로드 금지 — 이미지/볼륨 사전 준비 전제) | `backends/qwen_local.py` |
| 공용 HTTP 클라이언트 | `base_url`/`api_key` 인자 주입(환경변수 오염 없음 — pty·⑦응답 LLM과 격리) | `backends/openai_api.py` |

GPU 호스트에서 `docker compose up` 후, 백엔드 `.env`:

```
VLM_LIVE=1
VLM_TRACK=open
VLM_OPEN_BASE_URL=http://<gpu-host>:8001/v1
```

파인튜닝한 독자 모델로 교체 시: `models/waefer-vlm`의 가중치를 갈아끼우고 재빌드
(`docker compose build`) — 클라이언트는 무변경.

## 왜 가중치를 이미지에 굽는가(bake)

- 폐쇄망 팹 배포 전제: 레지스트리에서 이미지 pull 한 번이 배포의 전부가 되도록
  (외부 다운로드 경로 제거). `qwen_local.py`의 "런타임 다운로드 금지" 계약과 같은 원칙.
- 트레이드오프 인지: 이미지 ~27GB, 모델 교체마다 재빌드. 개발 환경에서는 공식 이미지
  + 캐시 볼륨 방식이 가볍다 — 이 패키징은 **운영 배포 형태**를 가정한 산출물이다.

## 현재 상태 · 발표 주장 수위 (0727 실측)

- ✅ **이미지 빌드 완료** — `waefer-vlm:0.1`, 콘텐츠 22.7GB
- ✅ **내용물 검증** — 컨테이너 내 `/models/waefer-vlm`에 safetensors 4샤드(17.1GB)
  + 토크나이저/설정 전부 실재 확인 (`docker run --rm --entrypoint ls ...`)
- ✅ **CPU 드라이런** — 컨테이너가 vLLM 기동 절차를 밟다가 정확히 GPU 미검출
  (`Failed to infer device type`)에서 정지 = GPU 없는 호스트의 유일한 올바른 실패 지점.
  엔트리포인트(`vllm serve` + 위치 인자 모델경로)·이미지 구조 정상.
  (⚠️ 첫 빌드에서 `--model` 플래그로 줬다가 위치 인자로 교정 — `vllm serve`는 positional)
- ✅ 클라이언트 전환 경로 코드 구현·병합 완료(PR #99) — 원격 모드는 OpenAI 호환이라
  데모의 pty 트랙과 동일한 클라이언트 경로
- ❌ **GPU 실기동·추론 미검증** — GPU 없음(교육 계정 g4dn 쿼터 제약). 운영 전환 단계 과제.
- 발표 표현: "독자 모델을 오프라인 패키징한 서빙 이미지를 빌드·구조 검증했고, 앱의 전환
  분기는 코드로 구현·병합됐다. GPU 실기동은 운영 전환 단계 과제다" — "추론까지 돌려봤다"고
  말하지 않는다.

## 보안 배치 원칙

- 서빙 컨테이너는 **프라이빗 서브넷**에 두고 8001은 앱 서버에서만 허용
  (웨이퍼맵 이미지가 지나가는 경로 — 외부 노출 금지)
- `VLM_OPEN_API_KEY`로 서버 토큰 검사 추가 가능(vLLM `--api-key`)
