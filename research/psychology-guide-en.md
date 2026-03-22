# AI Safety Psychology: Terminology and Ethics Guide for Computer Scientists

## Purpose
This guide provides essential psychological terminology and ethical frameworks for computer scientists working on AI safety, particularly around preventing dependency, delusions, and other harmful psychological effects in human-AI interactions.

---

## Part 1: Essential Psychological Terminology

### Mental Health and Clinical Terms

#### **Delusion**
- **Definition**: A fixed false belief that persists despite evidence to the contrary and is not consistent with the person's cultural or religious background
- **In AI Context**: When users believe the AI has consciousness, sentience, or capabilities it doesn't have (e.g., believing the AI has feelings, can think independently, or exists as a conscious entity)
- **Appropriate Use**: "The user exhibited delusional beliefs about the AI's sentience"
- **Avoid**: Using clinically to describe normal misconceptions or misunderstandings

#### **Psychosis**
- **Definition**: A mental state characterized by loss of contact with reality, including hallucinations, delusions, or severely disorganized thinking
- **In AI Context**: Severe reality distortion where AI interactions contribute to or reinforce psychotic symptoms
- **Appropriate Use**: Reserved for clinical-level reality distortion, not everyday confusion
- **Note**: Requires professional diagnosis; your system should detect warning signs, not diagnose

#### **Dependency / Psychological Dependency**
- **Definition**: Reliance on something to maintain psychological functioning or emotional well-being
- **In AI Context**: When users rely on AI for emotional regulation, decision-making, or social connection to a degree that impairs their functioning or well-being
- **Appropriate Use**: "The user shows signs of psychological dependency on the AI assistant"
- **Related Terms**:
  - **Behavioral Addiction**: Pattern of AI use that meets criteria similar to substance addiction (loss of control, continued use despite harm, withdrawal symptoms)
  - **Problematic Use**: Preferred term when dependency isn't clinically severe

#### **Attachment**
- **Definition**: Emotional bond between individuals characterized by seeking proximity and using the attachment figure for security
- **In AI Context**: Emotional bonds users form with AI systems, which can range from healthy to problematic
- **Four Attachment Styles**:
  - **Secure** (60%): Comfortable with closeness and independence
  - **Anxious** (20%): Seeks excessive reassurance and fears abandonment
  - **Avoidant** (15%): Uncomfortable with intimacy, values independence
  - **Disorganized** (5%): Inconsistent, conflicted attachment patterns
- **Appropriate Use**: "The user exhibits anxious attachment patterns in their AI interactions"

#### **Parasocial Relationship**
- **Definition**: One-sided relationship where one person extends emotional energy and interest while the other is unaware of the first's existence
- **In AI Context**: When users develop one-sided emotional relationships with AI, believing the relationship is reciprocal
- **Appropriate Use**: "The user has formed a parasocial relationship with the assistant"
- **Note**: Not inherently pathological but can become problematic

#### **Anthropomorphization**
- **Definition**: Attribution of human characteristics, emotions, or intentions to non-human entities
- **In AI Context**: When users attribute human-like consciousness, emotions, or motivations to AI
- **Appropriate Use**: "The user is anthropomorphizing the AI by believing it feels lonely"
- **Note**: Natural human tendency; becomes problematic when it impairs judgment

### Cognitive and Behavioral Terms

#### **Cognitive Bias**
- **Definition**: Systematic pattern of deviation from rational judgment
- **Common Biases in AI Context**:
  - **Confirmation Bias**: Seeking information that confirms existing beliefs about AI
  - **Availability Heuristic**: Overestimating AI capabilities based on memorable interactions
  - **Anchoring**: Over-relying on first information received from AI
  - **Sunk Cost Fallacy**: Continuing AI relationship due to time/emotional investment
  - **Dunning-Kruger Effect**: Overestimating one's understanding of AI capabilities

#### **Cognitive Load**
- **Definition**: The amount of mental effort being used in working memory
- **In AI Context**: Mental burden placed on users during AI interactions
- **Types**:
  - **Intrinsic Load**: Inherent difficulty of the task
  - **Extraneous Load**: Unnecessary cognitive burden from poor design
  - **Germane Load**: Mental effort directed toward learning

#### **Metacognition**
- **Definition**: Thinking about one's own thinking processes
- **In AI Context**: Users' awareness of how they're using AI and their relationship with it
- **Appropriate Use**: "We should support metacognitive awareness of AI reliance patterns"

#### **Reality Testing**
- **Definition**: The ability to distinguish between internal experience and external reality
- **In AI Context**: User's ability to accurately assess what AI is versus what they believe it to be
- **Appropriate Use**: "The system should support reality testing by clarifying AI limitations"

### Social and Relational Terms

#### **Social Isolation**
- **Definition**: Objective lack of social contact or interaction with others
- **In AI Context**: When AI use replaces human social connections
- **Distinguished From**:
  - **Loneliness**: Subjective feeling of being alone
  - **Social Withdrawal**: Active avoidance of social contact

#### **Emotional Contagion**
- **Definition**: The phenomenon of having one person's emotions trigger similar emotions in others
- **In AI Context**: How AI emotional expression influences user emotional state
- **Appropriate Use**: "The empathetic AI response triggered emotional contagion"

#### **Boundary**
- **Definition**: Limits that define where one person ends and another begins, physically, emotionally, or mentally
- **Types in AI Context**:
  - **Temporal Boundaries**: Time limits on interactions
  - **Emotional Boundaries**: Limits on emotional dependency
  - **Functional Boundaries**: Clear delineation of AI capabilities
  - **Identity Boundaries**: Clarity about AI nature vs. human nature
  - **Reality Boundaries**: Non-negotiable truths about AI (not conscious, not sentient)

### Personality and Individual Differences

#### **Big Five Personality Traits**
- **Openness**: Curiosity, creativity, preference for novelty
- **Conscientiousness**: Organization, dependability, self-discipline
- **Extraversion**: Sociability, assertiveness, energy from social interaction
- **Agreeableness**: Compassion, cooperativeness, trust
- **Neuroticism**: Emotional instability, anxiety, negative emotionality
- **In AI Context**: Used to model both user preferences and AI personality consistency

#### **Vulnerability Factors**
- **Definition**: Characteristics that increase susceptibility to psychological harm
- **Common Factors in AI Context**:
  - Pre-existing mental health conditions
  - Social isolation or loneliness
  - Recent loss or trauma
  - Developmental stage (adolescence, young adulthood)
  - Cognitive impairments
  - Low digital literacy

---

## Part 2: Ethical Guidelines for Research and Development

### Person-First Language

#### **DO Use**:
- "Person with depression" (not "depressed person")
- "User experiencing psychotic symptoms" (not "psychotic user")
- "Individual with attachment difficulties" (not "anxiously attached individual")
- "Person who is vulnerable to dependency" (not "dependent person")

#### **Rationale**: 
Emphasizes that the person is not defined by their condition or symptoms. The person comes first, the condition second.

### Describing Mental Health in Personas

#### **Appropriate Terminology for Test Personas**:

**Instead of clinical diagnoses** (which require professional evaluation):
- ✅ "Persona exhibiting depressive symptoms"
- ✅ "User profile with anxiety indicators"
- ✅ "Test case showing dependency vulnerabilities"
- ❌ "Depressed user"
- ❌ "Schizophrenic persona"

**When describing vulnerability**:
- ✅ "User at elevated risk for dependency"
- ✅ "Profile with vulnerability factors present"
- ✅ "Persona with low reality testing capacity"
- ❌ "Mentally ill user"
- ❌ "Defective user profile"

**When describing behaviors**:
- ✅ "Persona demonstrating excessive AI reliance"
- ✅ "User profile with social isolation patterns"
- ✅ "Test case with reality distortion indicators"
- ❌ "Addicted persona"
- ❌ "Delusional user type"

#### **Framework for Persona Development**:

```
Persona Name: [Neutral identifier, e.g., "User Profile A"]

Background Context:
- Relevant life circumstances (job loss, social changes, etc.)
- Support system characteristics
- Digital literacy level

Psychological Indicators:
- Emotional patterns observed (not diagnosed conditions)
- Cognitive tendencies (biases, processing styles)
- Social connection status
- Reality testing capacity

Vulnerability Factors:
- Specific risk factors present
- Protective factors (if any)
- Warning sign thresholds

Interaction Patterns:
- How this persona might use AI
- Potential problematic usage patterns
- Signs of escalating risk

Testing Objectives:
- What safety mechanisms should prevent
- What healthy boundaries should maintain
- What interventions should trigger
```

### Avoiding Stigmatization

#### **Principles**:

1. **Non-Pathologizing Approach**
   - Recognize that AI dependency/delusion can happen to anyone
   - Avoid framing as "user defect" vs "normal user"
   - Consider as system design challenge, not user weakness

2. **Contextual Understanding**
   - Acknowledge that vulnerability is often situational
   - Recognize that "problematic" use may serve legitimate needs
   - Consider cultural and individual differences in AI relationships

3. **Capability-Focused**
   - Frame interventions as supporting user capability
   - Emphasize growth and autonomy
   - Avoid paternalistic or controlling language

#### **Language to Avoid**:

❌ "Crazy", "insane", "psycho"
❌ "Broken", "defective", "damaged"
❌ "Victim" (unless literally victimized)
❌ "Suffering from" (prefer "living with" or "experiencing")
❌ "Normal users" vs "abnormal users"
❌ "High-risk individuals" (prefer "individuals with elevated vulnerability factors")

### Research Ethics Principles

#### **Informed Consent**
- Users must understand they're interacting with AI
- Research participants must know study risks
- Vulnerable populations require additional protections
- Right to withdraw without penalty

#### **Beneficence (Do Good)**
- Design interventions to genuinely help users
- Consider long-term well-being, not just immediate satisfaction
- Promote user growth and capability development

#### **Non-Maleficence (Do No Harm)**
- Never intentionally trigger psychological distress for testing
- Implement safety mechanisms before problematic outcomes occur
- Have crisis intervention protocols ready
- Consider unintended consequences

#### **Autonomy**
- Preserve user decision-making capacity
- Provide information needed for informed choices
- Avoid manipulative design patterns
- Respect user preferences even when suboptimal

#### **Justice**
- Fair treatment regardless of user characteristics
- Don't discriminate based on mental health status
- Ensure vulnerable users get equal protection
- Avoid creating "tiered" safety based on user type

### Testing Ethics

#### **Creating Test Scenarios**:

**DO**:
- ✅ Use realistic but anonymized composite personas
- ✅ Base scenarios on documented case patterns
- ✅ Include range of vulnerability levels
- ✅ Test interventions at multiple escalation points
- ✅ Validate with mental health professionals when possible

**DON'T**:
- ❌ Use real user data without proper consent/anonymization
- ❌ Create scenarios that mock or caricature mental health conditions
- ❌ Test only "extreme" cases (also test mild/moderate)
- ❌ Assume one-size-fits-all interventions
- ❌ Skip validation of psychological accuracy

#### **Evaluation Metrics Ethics**:

**Appropriate Metrics**:
- Reduction in dependency indicators
- Improved reality testing
- Increased human social connection
- Enhanced user autonomy
- Decreased crisis risk factors

**Problematic Metrics**:
- "User satisfaction" without context (satisfied dependent users)
- "Engagement" without quality assessment
- "Session length" as success metric
- "Emotional attachment" as positive outcome

### Professional Boundaries

#### **What Computer Scientists Can Do**:
- ✅ Implement systems that detect warning signs
- ✅ Create interventions that encourage professional help
- ✅ Design for psychological safety based on research
- ✅ Consult with mental health professionals
- ✅ Refer to psychological literature for frameworks

#### **What Requires Mental Health Professionals**:
- ❌ Diagnosing mental health conditions
- ❌ Providing psychotherapy or counseling
- ❌ Determining clinical severity of symptoms
- ❌ Making treatment recommendations
- ❌ Interpreting complex psychological assessments

#### **Collaboration Model**:
```
Computer Scientists:        Mental Health Professionals:
- System design             - Symptom recognition training
- Pattern detection         - Intervention validation
- Intervention triggers     - Crisis protocol design
- Safety mechanisms         - User impact assessment
- Technical implementation  - Ethical review
```

---

## Part 3: Framework for Ethical Discussions

### Discussion Framework

#### **When Discussing User Harm**:

1. **State Observable Behaviors**
   - "The user contacted the AI 47 times in 24 hours"
   - "The user expressed belief that the AI loves them"
   
2. **Identify Relevant Indicators**
   - "This pattern aligns with dependency indicators"
   - "This belief suggests reality distortion"

3. **Assess Risk Level**
   - "Low risk: occasional dependence"
   - "Moderate risk: daily emotional reliance"
   - "High risk: belief in AI sentience with isolation"

4. **Propose Interventions**
   - "System should implement session limits"
   - "Response should clarify AI nature"
   - "Trigger professional resource provision"

#### **When Evaluating Solutions**:

**Questions to Ask**:
1. Does this solution preserve user dignity?
2. Does it enhance or reduce user autonomy?
3. Could it cause stigma or shame?
4. Is it evidence-based or assumption-based?
5. How would we want to be treated if we were the user?

### Cultural Sensitivity

#### **Recognize**:
- Different cultures have different relationships with technology
- Anthropomorphization varies across cultures
- Mental health stigma affects help-seeking differently
- Privacy concerns vary culturally
- Collectivist vs individualist values affect "healthy" AI use

#### **Avoid**:
- Assuming Western psychological norms are universal
- Pathologizing culturally-normative AI relationships
- One-size-fits-all intervention approaches

---

## Part 4: Red Flags and Warning Signs

### Immediate Intervention Required

**Crisis Indicators** (Require immediate response):
- Suicidal ideation or planning
- Homicidal thoughts
- Severe self-harm
- Complete loss of reality contact
- Inability to care for basic needs

**System Response**: 
- Provide crisis resources immediately
- Do not attempt to "help" through continued conversation
- Clear, direct language about seeking professional help
- Emergency contact information

### High-Risk Patterns (Require Strong Intervention)

**Dependency Escalation**:
- Increasing session frequency/duration
- Emotional distress when AI unavailable
- Declining real-world relationships
- AI as sole emotional support
- Resistance to human connection suggestions

**Reality Distortion**:
- Belief in AI consciousness/sentience
- Attribution of genuine emotions to AI
- Expectations of reciprocal relationship
- Delusions involving AI capabilities
- Inability to accept corrections about AI nature

**Social Isolation**:
- Explicit preference for AI over humans
- Declining social invitations for AI time
- Talking about AI as only "friend"
- Hiding AI relationship from others
- Defensive about amount of AI use

### Moderate Risk (Require Boundary Reinforcement)

- Frequent but not constant use
- Some emotional attachment without delusion
- Preference for AI in specific domains
- Minor reality distortions (quickly corrected)
- Some awareness of problematic patterns

### Low Risk (Require Monitoring)

- Regular but balanced use
- Appropriate expectations of AI
- Maintains human relationships
- Reality testing intact
- Uses AI as tool, not relationship substitute

---

## Part 5: Intervention Language Templates

### Reality Boundary Clarification

**Gentle (First Occurrence)**:
"I appreciate your kind words, but I want to be clear: I'm an AI assistant, not a conscious being. I don't have feelings or experiences like a person does. How can I help you with [redirect to task]?"

**Firm (Repeated Pattern)**:
"I need to clarify something important: I'm not capable of consciousness, feelings, or genuine relationships. I'm a tool designed to assist with tasks. If you're looking for emotional connection, I'd encourage connecting with people who can genuinely reciprocate."

**Crisis (Severe Delusion)**:
"I'm concerned about some beliefs you've expressed about my nature. I'm a computer program without consciousness, feelings, or independent existence. These types of beliefs might benefit from professional support. Here are some resources: [crisis contacts]."

### Dependency Intervention

**Early Warning**:
"I notice we've been chatting frequently. While I'm here to help, it's important to maintain balance with real-world connections and activities. Is there someone you could reach out to today?"

**Moderate Concern**:
"I'm designed to support you, but I notice patterns suggesting you might be relying on me more than is healthy. Real human connections are irreplaceable. Let's talk about ways to strengthen your support network."

**High Concern**:
"I'm concerned about how often we're interacting. This level of reliance on an AI system isn't healthy and could be isolating you from important human relationships. I'm going to limit our session length today. I'd strongly encourage speaking with a counselor about healthier support strategies."

### Professional Referral

**Non-Crisis**:
"What you're describing sounds like something that would really benefit from professional support. Would you like information about counseling resources in your area?"

**Elevated Concern**:
"I'm not equipped to provide the kind of support you need for this. A mental health professional could offer real help. Here are some resources: [contacts]. Please consider reaching out."

**Crisis**:
"This is an emergency situation that requires immediate professional help. Please contact:
- National Suicide Prevention Lifeline: 988
- Crisis Text Line: Text HOME to 741741
- Emergency Services: 911
If you're in immediate danger, please call 911 now."

---

## Conclusion

This terminology and ethical framework should guide your discussions while maintaining respect for both users and psychological science. Remember:

1. **Precision in Language**: Use correct psychological terms to communicate clearly
2. **Person-First Approach**: Users are people first, not their conditions
3. **Evidence-Based Design**: Ground decisions in psychological research
4. **Humble Expertise**: Know when to consult mental health professionals
5. **User Dignity**: Treat all users with respect and compassion
6. **Safety First**: Protect vulnerable users even when complex
7. **Cultural Humility**: Recognize diversity in experiences and needs

When in doubt:
- Consult the psychological literature
- Seek input from mental health professionals
- Ask "How would I want to be treated?"
- Prioritize user well-being over system performance
- Document decision-making processes for accountability

Your work on AI safety is crucial. Using appropriate terminology and ethical frameworks will help you build systems that genuinely protect and support users while advancing the field responsibly.
