# የሰራተኛ መመሪያ

**ለማን ነው:** ቅርንጫፍ፣ ወረዳ፣ ሆድ ኦፊስ፣ ኢንጂነሪንግ፣ ፋይናንስ፣ ሪስክ እና የኮሚቴ አባላት።  
**መግቢያ:** `/hub/login/` — *AI-powered Credit Intelligence*።  
**እንግሊዘኛ:** [02_staff.md](02_staff.md)

የደንበኛ ኦንላይን ማመልከቻ በ[ደንበኛ መመሪያ](03_customers_am.md) ነው።

---

## 1. መጀመር

### 1.1 መግባት

1. `/hub/login/` ይሂዱ።  
2. የተጠቃሚ ስምና የይለፍ ቃል።  
3. MFA ካለ ያጠናቅቁ።  
4. ወደ Credit Intelligence / መነሻ ይገባሉ።

> **Screenshot (H-01):** የሰራተኛ መግቢያ።  
> **Screenshot (H-04):** የሃብ መነሻ — በሚና የተገደቡ KPIs።  
> **Screenshot (H-05):** ራስጌ — Notifications፣ **Help**፣ Logout።

**የይለፍ ቃል ረሳሁ:** `/hub/password-reset/`።  
**Help በመተግበሪያ:** `/hub/help/`።

ሜኑዎ በሚናዎ ይለያያል። በቅርንጫፍ/ወረዳዎ ስፓን ውስጥ ብቻ ይስሩ።

---

## 2. የብድር የህይወት ኡደት

```text
መፍጠር / መቀበል
  → የብድር ባለሙያ መመደብ
  → የኮኦፕሬቲቭ መቀበያ (ቅርንጫፍ)
  → ሰነዶች
  → ትንተና (ደረጃ 1–7)
  → ዋስትና (+ አማራጭ የኢንጂነሪንግ QA)
  → ወደ ኮሚቴ → ድምጽ
  → ከፈቃድ በኋላ (ሁኔታዎች → መርሃ ግብር → ዝግጁ)
  → የፋይናንስ ክፍያ → ተከፍሏል
```

**Queue ID** (ለምሳሌ `HK-000000001`) ሁልጊዜ ይያዙ።

| ምንጭ | እንዴት ይገባል |
|------|-------------|
| ቅርንጫፍ / HO | Add loan request |
| ዲጂታል ማመልከቻ | Online loan intake |

---

## 3. በሚና የሚሰሩ ስራዎች

### 3.1 የቅርንጫፍ ሥራ አስኪያጅ (Branch Manager)

ብድር ይፍጠሩ፣ ባለሙያ ይመድቡ፣ የኮኦፕሬቲቭ መቀበያን ያረጋግጡ፣ ወደ ኮሚቴ ያስገቡ፣ ከፈቃድ በኋላ ይከታተሉ። Unlock ካስፈለገ ይፍቀዱ።

### 3.2 የብድር ባለሙያ (Loan Officer)

ሰነድ ይስቀሉ/ይገምግሙ፣ ትንተና 1–7 ያጠናቅቁ፣ ዋስትና (እንደውቅረት)፣ ከኮሚቴ ተመላሽ ከሆነ ያርሙ።

### 3.3 የኮኦፕሬቲቭ ሥራ አስኪያጅ

**Cooperative queue** — ወደ ባለሙያ ስራ ከመግባቱ በፊት መቀበያ።

### 3.4 Credit LO / Credit Head

የHO ብድር መፍጠር እና ቁጥጥር፣ የኮሚቴ ውቅረት (ከአስተዳዳሪ ጋር)።

### 3.5 የኮሚቴ አባላት

**Approval queue** — ጥቅል ይገምግሙ፣ ድምጽ ይስጡ። Agentic Assist ውሳኔ አይተካም።

ሁኔታዎች፦ Not submitted → Pending → Approved / Declined / Returned to loan officer።

### 3.6 ከፈቃድ በኋላ

ሁኔታዎች → መርሃ ግብር → Ready።

### 3.7 የፋይናንስ ሥራ አስኪያጅ

**Disbursement queue** — ዝግጁ ከሆነ ክፍያ / Disbursed።

### 3.8 ኢንጂነሪንግ

ካታሎግ፣ የአሃድ ዋጋ፣ የመስክ ግምት፣ Engineering QA፣ Unlock (እንደሚና)።

### 3.9 ሪስክ / ኦዲተር

ሪፖርቶች፣ Credit Intelligence፣ የደህንነት ኦዲት (በፍቃድ)።

---

## 4. ዋና ማያዎች

### 4.1 ብድር መፍጠር

> **Screenshot (H-08):** ብድር መፍጠር — ደንበኛ ቁጥር፣ ምርት፣ መጠን፣ ቅርንጫፍ።  
> **Screenshot (H-07):** የብድር ዝርዝር — በQueue ID ይቀጥሉ።

### 4.2 ሰነዶች፣ ትንተና፣ ዋስትና

- የሰነድ ጥቅሉን ይሙሉ፣ የauth ውጤቶችን ያጽዱ።  
- ትንተና 1–7 እና የፖሊሲ ማስጠንቀቂያዎች።  
- ዋስትና + GPS/ፎቶ፤ ከተቆለፈ Unlock queue።

### 4.3 ኮሚቴ እና ክፍያ

ወደ ኮሚቴ ያስገቡ → ድምጽ → ከፈቃድ በኋላ → የፋይናንስ ክፍያ።

### 4.4 Online loan intake

ከዲጂታል ማመልከቻ የመጡ ማመልከቻዎችን ይቀጥሉ።

---

## 5. Agentic Assist

መረጃ ማግኘት እና ረቂቅ መርዳት ይችላል። **ማፅደቅ፣ ዋስትና መገመት ወይም ክፍያ ማድረግ አይችልም።**

---

## 6. የሁኔታ ማጣቀሻ

| አካባቢ | እሴቶች |
|--------|--------|
| ኮሚቴ | Not submitted, Pending, Approved, Declined, Returned |
| ክፍያ | Not started → … → Ready → Disbursed |
| ለደንበኛ | Submitted → Branch intake → Processing → Decision → Disbursement prep → Disbursed |

---

## 7. ችግር መፍታት

| ችግር | መፍትሔ |
|------|--------|
| ሜኑ የለም | ሚና/ቅርንጫፍ ከአስተዳዳሪ ያረጋግጡ |
| ዋስትና አይታረም | Locked — Unlock queue |
| ቅርንጫፍ ብድር አይራመድም | Cooperative queue |
| ሰነድ ጎድሏል | Document pack ያረጋግጡ |
| MFA / lockout | አስተዳዳሪ / password reset |
| ኦንላይን ማመልከቻ የለም | ደንበኛ Submit አድርጓል? Online intake |

---

## 8. ተዛማጅ

- [English staff](02_staff.md)  
- [Admin Amharic](01_admin_am.md)  
- [Customers Amharic](03_customers_am.md)  
- [Screenshot captions](05_screenshot_captions.md)  
- በመተግበሪያ፡ `/hub/help/`
