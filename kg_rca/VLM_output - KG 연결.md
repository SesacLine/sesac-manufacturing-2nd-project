Wafer map 이미지·die matrix
→ ① VLM 원시 판독
→ ② 정량값 계산
→ ③ 자연어 정규화·KG 매핑
→ ④ 스키마·의미 검증
→ ⑤ KG 전달 JSON

- 기획원본
    
    ```
    {
      "patterns": ["Edge-Ring"],
      "spatial": {"zone": "edge", "direction": "전방위", "shape": "ring"},
      "description": "웨이퍼 가장자리를 따라 링 형태로 불량 die가 밀집한다. 불량 die 비율은 약 18.0%이다.",
      "severity": {"defect_die_ratio": 0.18},
      "confidence": "high",
      "ambiguity": null
    }
    ```
    

### 1. VLM output

```sql
{
  "pattern_candidate": "Edge-Ring", #고정-CNN결과값
  "location_text": "불량 die가 웨이퍼 가장자리 둘레 전체에 분포한다.",
  "morphology_text": "조밀한 불량 die가 거의 끊김 없는 원형 띠를 형성한다.",
}
```

**+) vlm output 검증 레이어 기획 필요**

- **패턴별 고정 루브릭 3개 필요, VLM 출력 자동 검증 → 기준 미달 시 재생성 또는 검토 로직 설계**
- 참고: WaferSAGE 프롬프트
    
    ```
    귀하는 반도체 웨이퍼 결함 분석 전문가입니다. 제공된 웨이퍼 맵 이미지를 분석하고 다음 사항을 설명하십시오. 
    
    1. 공간 분포: 결함은 어디에 위치해 있습니까? (중심, 가장자리, 특정 영역, 클록 위치) 
    2. 형태: 결함은 어떤 모습입니까? (패턴, 모양, 밀도, 질감) 
    
    공간적 및 형태적 특성에만 초점을 맞춰 간결한 기술적 설명을 제공하십시오. 근본 원인 분석은 포함하지 마십시오.
    
    You are a semiconductor wafer defect analysis expert. Analyze the provided
    wafer map image and describe:
    
    **1. Spatial Distribution: Where are the defects located? (center, edge, specific regions, clock positions)
    2. Morphology: What do the defects look like? (patterns, shapes, density, texture)**
    
    Provide a concise technical description focusing only on spatial and morphological characteristics. Do not include root cause analysis.
    ```
    
- 참고: WaferSAGE 루브릭
    
    ```
    {
      "defect_types": ["list of defect types present"],
      "spatial_rubric": {
        "zone": "affected zones description",
        "distribution": "distribution pattern description",
        "clock_position": "clock positions mentioned",
        "coordinates_hint": "coordinate references",
        "spatial_avoid": ["terms that should NOT appear"]
      },
      "morphology_rubric": {
        "pattern_type": "pattern descriptions",
        "density": "density descriptions",
        "geometric_structure": "geometric terms",
        "texture_description": "texture terms",
        "morphology_avoid": ["terms that should NOT appear"]
      },
      ~~"root_cause_rubric": {
        "equipment_category": "equipment types involved",
        "process_step": "process steps involved",
        "potential_causes": ["list of potential causes"],
        "root_cause_avoid": ["terms that should NOT appear"]
      },~~
      "summary": "brief description of overall defect pattern"
    }
    ```
    
    ```
    { 
      "결함 유형": ["존재하는 결함 유형 목록"], 
      **"공간적 기준"**: { 
        "구역": "영향을 받는 구역 설명", 
        "분포": "분포 패턴 설명", 
        "시계 위치": "언급된 시계 위치", 
        "좌표 힌트": "좌표 참조", 
        "공간적 회피": ["나타나서는 안 되는 용어"] 
      }, 
      **"형태학적 기준"**: { 
        "패턴 유형": "패턴 설명", 
        "밀도": "밀도 설명", 
        "기하학적 구조": "기하학적 용어", 
        "텍스처 설명": "텍스처 용어", 
        "형태학적 회피": ["나타나서는 안 되는 용어"] 
      }, 
      ~~"근본 원인 기준": { 
        "장비 범주": "관련 장비 유형", 
        "프로세스 단계": "관련 프로세스 단계", 
        "잠재적 원인": ["잠재적 원인 목록"] 원인"], 
        "근본 원인 방지": ["나타나서는 안 되는 용어"] 
      },~~ 
      "요약": "전반적인 결함 패턴에 대한 간략한 설명" 
    }
    ```
    
    ```
    {
      "defect_types": ["Center", "Edge-Ring", "Loc", "Scratch"],
      "spatial_rubric": {
        **"zone":** "Center, Edge, Mid-radius, Lower hemisphere",
        "**distribution":** "Multi-modal, High-density cluster, Edge-ring pattern",
        "**clock_position":** "Lower hemisphere, Upper-left quadrant",
        **"coordinates_hint":** "Center (0,0)",
        **"spatial_avoid":** ["Top-right quadrant", "Uniform distribution"]
      },
      "morphology_rubric": {
        "pattern_type": "Amorphous blob, Continuous band, Linear feature",
        "density": "High-density, Medium-density",
        "geometric_structure": "Cluster, Ring, Linear",
        "texture_description": "Dense amorphous, Sharp continuous linear",
        "morphology_avoid": ["Circular", "Radial", "Grid-like"]
      },
      ~~"root_cause_rubric": {
        "equipment_category": "Wet process tool, Deposition/Etch tool",
        "process_step": "Deposition, Etch, Wafer handling",
        "potential_causes": [
          "Non-uniformity in wet process",
          "Thermal gradient during Deposition/Etch",
          "Mechanical handling error"
        ],
        "root_cause_avoid": ["Photolithography misalignment", "Over-etch"]
      }~~
    }
    ```
    

### 2. die matrix 또는 segmentation 결과를 이용해 계산 (VLM에 맡기지 않음)

(vlm 이후 파트 - 그룹이라 평균 계산을 해야할지..)

```sql
{
  "defect_die_count": 92,
  "total_die_count": 512,
  "defect_die_ratio": 0.1796875,
  "radial_distribution": {
    "center_ratio": 0.03,
    "interior_ratio": 0.07,
    "edge_ratio": 0.9
  },
  "occupied_clock_positions": [
    1, 2, 3, 4, 5, 6,
    7, 8, 9, 10, 11, 12
  ]
}
```

---

### 3. VLM 후처리 레이어: VLM 자연어와 계산 결과를 함께 사용해 KG용 enum으로 변환

```sql
{
  "**pattern": "Edge-Ring",**
  **"spatial"**: {
    "zones": ["edge"],                //center | interior | edge | unknown
    "angular_coverage": "full",       //full | partial | unknown
    "clock_positions": []             //1~12, 중복 허용
  },
    **"morphology"**: {
      "shapes": ["ring"],   //blob | line | arc | ring | band | no_dominant_shape | other | unknown
      "density": "high",        //high | medium | low | unknown
      "continuity": "continuous" //continuous | intermittent | discontinuous | not_applicable | unknown
    }
  "mapping": {
    "status": "mapped",
    "zone_source": "calculated",
    "shape_source": "vlm_text",
    "unmapped_terms": []
  }
}
```

- `clock_positions` 규칙
    
    ```sql
    angular_coverage=full
    → clock_positions=[]
    
    angular_coverage=partial
    → clock_positions=[해당 방향]
    
    angular_coverage=unknown
    → clock_positions=[]
    ```
    
- 4. 검증 규칙
    
    ```sql
    pattern은 단일 값이며 MVP 허용 목록에 포함
    pattern이 None이면 spatial·morphology는 null 또는 not_applicable
    ~~status=confident이면 alternative_patterns는 빈 배열
    status=ambiguous이면 alternative_patterns가 한 개 이상~~
    angular_coverage=partial이면 clock_positions가 한 개 이상
    angular_coverage=full이면 clock_positions는 빈 배열
    zones에 full 사용 불가
    ```
    

### 5. KG 최종 전달

**`observation`이 UI나 KG 설명용으로 필요하다면 VLM이 별도로 생성하는 게 아니라, 정규화가 완료된 뒤 템플릿으로 조합 (location_text+morphlogy_text)**

```sql
{zone_표현}를 따라 {density_표현}하고 {continuity_표현}인 {shape_표현} 형태의 불량 die가 관찰된다.
```

```sql
{
  "schema_version": "wafer-observation-v1",
  "pattern": "Edge-Ring",
  "spatial": {
    "zones": ["edge"],
    "angular_coverage": "full",
    "clock_positions": []
  },
  "morphology": {
    "shape": "ring",
    "density": "high",
    "continuity": "continuous"
  },
  "quantitative": {
    "defect_die_count": 92,
    "total_die_count": 512,
    "defect_die_ratio": 0.1796875
  },
  "observation": "웨이퍼 가장자리 둘레 전체에 걸쳐 조밀하고 연속적인 링 형태의 불량 die가 관찰된다.",
  "provenance": {
    "pattern_source": "vlm",
    "spatial_source": "die_matrix_statistics",
    "morphology_source": "vlm_normalization",
    "quantitative_source": "die_matrix_statistics"
  },
  "validation": {
    "schema_valid": true,
    "semantic_valid": true,
    "warnings": []
  },
  "meta": {
    "model": "qwen3-vl-4b",
    "prompt_version": "v1",
    "mapping_version": "wafer-mapper-v1",
    "zone_schema_version": "wafer-zone-v1"
  }
}
```

- provenance: 각 값이 어디서 왔는지를 남겨 오류났을 때 어느 단계까 문제였는지 추적
- validation; KG에 넣어도 될 값인지 품질 게이트 (angular_coverage = full, clock_positions 일부만 들어가는 식 논리 충돌 검증)
- meta: 재현성/버전관리 목적