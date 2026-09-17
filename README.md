<div align="center">

# PathGuard AI

### AR 기반 드라이빙 보조 시스템

**AI Object Detection · P2P Network · AR Visualization**

> 차량 간 시야를 공유해 운전자가 직접 볼 수 없는 위험까지  
> 실시간으로 인지할 수 있도록 설계한 드라이빙 보조 시스템입니다.

**SUMTECH HACKATHON 2025 · 최우수상**

</div>

---

## Overview

기존 ADAS는 차량 자체의 카메라와 센서에 의존하기 때문에  
대형 차량이나 건물 등에 가려진 **사각지대의 위험 요소를 인식하기 어렵다는 한계**가 있습니다.

**PathGuard AI**는 이를 해결하기 위해

```text
AI 객체 인식
    +
차량 간 P2P 시야 공유
    +
AR 실시간 시각화
```

를 결합했습니다.

주변 차량이 탐지한 위험 정보를 서로 공유하고,  
통합된 위험 정보를 AR 디바이스에 표시해  
운전자에게 **보이지 않는 위험까지 확장된 시야로 제공**하는 것을 목표로 했습니다.

---

## Key Features

### AI Sentry

차량 카메라와 센서 데이터를 기반으로 도로 위 객체를 분석합니다.

- 차량·보행자·이륜차·장애물 인식
- 객체 위치 분석
- 속도 및 이동 방향 추정
- 충돌 위험 판단

### P2P Vision Sharing

주변 차량이 인식한 위험 정보를 실시간으로 공유합니다.

- 차량 간 위험 데이터 공유
- 주변 차량의 시야 정보 결합
- 사각지대 보완
- 중앙 서버 의존도를 낮춘 분산형 구조

### AR Visualization

통합된 위험 정보를 **HoloLens**를 통해 운전자 시야에 표시합니다.

- 위험 요소 위치 시각화
- 우선순위가 높은 위험 정보 표시
- 운전자 시야 기반 직관적 경고 제공

---

## System Flow

```text
차량 카메라 · 센서
        ↓
AI 객체 인식
        ↓
위치 · 속도 · 방향 분석
        ↓
충돌 위험도 판단
        ↓
P2P 차량 간 위험 정보 공유
        ↓
내 차량 시야 + 주변 차량 시야 통합
        ↓
AR 디바이스(HoloLens)
        ↓
실시간 위험 시각화
```

> **내 시야 + 다른 차량의 시야 = 확장된 시야**

---

## Tech Stack

| Area | Technology |
|---|---|
| AI / Backend | Python |
| Input | 차량 카메라 및 센서 데이터 |
| Network | P2P / Mesh Network |
| Visualization | AR, HoloLens |
| Data | 객체 위치 · 속도 · 이동 방향 · 위험도 |

---

## My Contribution

> 이 부분은 본인이 실제 담당한 내용을 기준으로 작성해주세요.

- `[담당 기능 1]`
- `[담당 기능 2]`
- `[담당 기능 3]`
- `[팀원과 연동하거나 조율한 부분]`

---

## Result

- **SUMTECH HACKATHON 2025 최우수상**
- AI · Network · AR을 결합한 드라이빙 보조 시스템 설계
- 차량 간 **Cooperative Perception** 구조 적용
- 사각지대 위험을 차량 간 공유하는 실시간 서비스 흐름 구현
- AI 객체 인식, P2P 공유, AR 시각화 Demo 제작

---

## What I Learned

짧은 해커톤 기간 동안 개별 기술을 구현하는 것보다  
**AI 객체 인식, 차량 간 통신, AR 시각화가 하나의 서비스 흐름으로 연결되도록 설계하는 과정**이 중요하다는 것을 경험했습니다.

특히 기존 ADAS의 한계를 먼저 정의하고  
여러 기술을 결합해 이를 해결하는 구조를 설계하면서  
기술 자체보다 **문제를 해결하기 위한 시스템 구성과 연결 방식**을 고민할 수 있었습니다.

---

<div align="center">

### PathGuard AI

**See Beyond Your Sight.**

</div>
