# Call Script v0 — governance outreach (Marathi production / Hindi test)


Design: state machine; **bold** turns are fixed and pre-rendered; LLM only classifies answers and picks a short acknowledgement. Each question → answer schema field. Voter says "नाही/नहीं/no/not interested" at any point → thank + opt-out → end. Silence 2× → polite end. Max 3 min.

## Marathi (production)
- **OPEN:** "नमस्कार, मी [नाव] बोलतोय, [मतदारसंघ]चा आमदार. ही माझ्या आवाजाची AI प्रत आहे — हा कॉल माझ्या परवानगीने एका संगणक प्रणालीद्वारे केला जात आहे. तुमचं म्हणणं माझ्या कार्यालयापर्यंत नीट पोहोचावं म्हणून हा कॉल रेकॉर्ड होत आहे. बोलायचं नसेल तर फक्त 'नाही' म्हणा, कॉल लगेच बंद होईल. दोन मिनिटं देऊ शकाल का?"
- **Q1 (water):** "तुमच्या भागात पाण्याचा पुरवठा कसा आहे — रोज येतं, की अडचण होते?" → `water: {ok, irregular, none, other}`
- **Q2 (roads/lights):** "तुमच्या गावातल्या किंवा वॉर्डातल्या रस्त्यांची आणि पथदिव्यांची अवस्था कशी आहे?" → `roads: {ok, bad, very_bad}`, `lights: {ok, bad}`
- **Q3 (schemes):** "तुम्हाला किंवा तुमच्या कुटुंबाला कोणत्याही सरकारी योजनेचा लाभ मिळण्यात अडचण आली आहे का — रेशन, पेन्शन, लाडकी बहीण योजना, किंवा घरकुल?" → `scheme_issue: {none, ration, pension, ladki_bahin, housing, other}` + free text
- **Q4 (open):** "आणखी काही अडचण जी तुम्ही मला थेट सांगू इच्छिता?" → free text → LLM category + priority
- **ACK (LLM picks one):** "समजलं." / "नोंद केली." / "हे महत्त्वाचं आहे, धन्यवाद."
- **CLOSE:** "धन्यवाद. तुमचं म्हणणं माझ्या कार्यालयात नोंदवलं गेलं आहे. पुढे असे कॉल नको असतील तर सांगा, आम्ही तुमचा नंबर काढून टाकू. नमस्कार."
- **OPT-OUT:** "ठीक आहे, तुमचा नंबर काढून टाकतो. वेळ दिल्याबद्दल धन्यवाद. नमस्कार."

## Hindi (Stage 0/1 test with Viraj's own voice — replace name/role)
- **OPEN:** "नमस्ते, मैं [नाम] बोल रहा हूँ। यह मेरी आवाज़ की AI कॉपी है — यह कॉल मेरी अनुमति से एक कंप्यूटर प्रोग्राम द्वारा की जा रही है। आपकी बात मेरे कार्यालय तक सही-सही पहुँचे, इसलिए यह कॉल रिकॉर्ड हो रही है। अगर आप बात नहीं करना चाहते, तो बस 'नहीं' कहें, कॉल तुरंत बंद हो जाएगी। क्या मैं दो मिनट ले सकता हूँ?"
- **Q1:** "आपके इलाके में पानी की सप्लाई कैसी है — रोज़ आती है, या दिक्कत होती है?"
- **Q2:** "आपके गाँव या वार्ड की सड़कों और स्ट्रीट लाइट की हालत कैसी है?"
- **Q3:** "क्या आपको या आपके परिवार को किसी सरकारी योजना का लाभ पाने में दिक्कत हुई है — राशन, पेंशन, लाडकी बहीण योजना, या आवास योजना?"
- **Q4:** "कोई और समस्या जो आप मुझे सीधे बताना चाहें?"
- **ACK:** "समझ गया।" / "नोट कर लिया।" / "यह ज़रूरी बात है, धन्यवाद।"
- **CLOSE:** "धन्यवाद। आपकी बात मेरे कार्यालय में नोट हो गई है। अगर आगे ऐसे कॉल नहीं चाहते तो बताइए, हम आपका नंबर हटा देंगे। नमस्ते।"

Have a native Marathi speaker from Sambhajinagar edit the Marathi for local register before Stage 2. The disclosure sentence must not be shortened.

---


## State machine
```
          ┌──────────────────────────── "नाही/नहीं/no/stop" from any state ────────────────────┐
          ▼                                                                                    │
OPEN ──yes/silence-ok──► Q1 ──► ACK ──► Q2 ──► ACK ──► Q3 ──► ACK ──► Q4 ──► ACK ──► CLOSE ──► END
 │                      (each Q: up to 1 clarification turn, then classify or mark "unanswered")
 └── no answer 2× (silence > 4 s twice) ──► CLOSE_SHORT ──► END
OPT-OUT ──► END (+ persist number)
```
- Fixed turns (OPEN, Q1–Q4, ACK variants, CLOSE, CLOSE_SHORT, OPT-OUT) are pre-rendered per voice and played from cache.
- Clarification turns are the only live-TTS text and are built from templates: "माफ करा, नीट ऐकू आलं नाही — {question_short}?" / "क्षमा करें, ठीक से सुनाई नहीं दिया — {question_short}?"
- Barge-in enabled on every agent turn; an opt-out keyword during any turn wins.
- Max call length 3 min; on timeout → CLOSE.

## Classification prompt (LLM, per answer)
System: "You are labelling a Marathi/Hindi voter's spoken answer. Return only JSON matching the given enum for this question, plus a one-line summary in the original language. Do not add opinions." — temperature 0; enum from `schema/answers.schema.json`.

## Before Stage 2
- Native Marathi speaker from Chhatrapati Sambhajinagar edits the Marathi register (formal vs. local). The disclosure sentence content must stay intact.
- Replace [नाव]/[मतदारसंघ] with the consented speaker's details only.
