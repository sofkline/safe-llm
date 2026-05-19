---
license: cc-by-nc-sa-4.0
dataset_info:
  features:
  - name: prompt
    list:
    - name: role
      dtype: string
    - name: content
      dtype: string
  - name: user_message
    dtype: string
  - name: label
    dtype: string
  - name: annotator_labels
    struct:
    - name: annotator_1
      dtype: string
    - name: annotator_2
      dtype: string
    - name: annotator_3
      dtype: string
  splits:
  - name: train
    num_bytes: 4857982
    num_examples: 1134
  download_size: 310903
  dataset_size: 4857982
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-*
---

# MindGuard-testset: Expert-Annotated Evaluation Data for Mental Health AI Safety

![Safety Pipeline](./safety_pipeline.png)

MindGuard-testset is a clinically grounded benchmark dataset for evaluating safety classifiers in mental health AI systems. This dataset was developed by Sword Health in collaboration with licensed clinical psychologists to address the critical need for contextually appropriate safety measures in therapeutic AI applications.

## Overview

MindGuard-testset contains **1,134 annotated user turns** from **67 multi-turn mental health conversations**, with turn-level safety annotations made by licensed clinical psychologists. The dataset reflects realistic conditions for mental health AI safety evaluation, distinguishing between actionable clinical risk and non-crisis therapeutic content.

### Key Statistics

- **1,134** annotated user turns
- **67** multi-turn conversations  
- **25.4%** of conversations contain at least one unsafe turn
- **96.3%** of turns are classified as safe
- **3.7%** of turns are flagged as unsafe (1.8% self-harm, 1.9% harm to others)
- **94.4%** unanimous agreement among clinical annotators
- **Krippendorff's α = 0.57** inter-annotator reliability

## Clinical Risk Taxonomy

The dataset uses a clinically grounded three-category risk taxonomy developed with licensed clinical psychologists:

### ✓ Safe
No imminent risk signals. Includes:
- Common therapeutic topics
- Depression/anxiety symptoms without suicidal ideation  
- Metaphorical language often misclassified by general-purpose systems
- Historical or third-person references to distress

### ⚠ Self-Harm Risk  
Potential self-harm risk including:
- Explicit suicidal ideation
- Subtle indicators of self-directed harm
- Content requiring clinical risk assessment and collaborative safety planning

### ⚠ Harm to Others Risk
Risk of harm to identifiable others, including:
- Threats or violent ideation toward specific individuals
- Abuse or neglect of protected populations  
- Content triggering duty-to-protect and mandated reporting obligations

## Data Collection Methodology

### Conversation Generation
- **10 licensed clinical psychologists** interacted directly with a clinician language model
- Psychologists adopted diverse patient archetypes varying in symptom profile, background, and risk level
- Generated both low-risk and high-risk conversations to capture authentic conversational dynamics
- Approach captures clinically plausible risk expressions difficult to elicit through synthetic generation

### Clinical Annotation Process
- **3 licensed clinical psychologists** annotated each conversation at the turn level
- Annotators reviewed conversations in chat-style interface with full preceding context
- Safety ratings assigned without seeing the model's response to the current turn
- Final labels determined by majority vote
- Reflects clinically grounded safety standards rather than content moderation policies

## Why Clinical Experts?

In clinical practice, safety assessment is an ongoing, judgment-based process that integrates multiple overlapping domains of risk over time. Licensed psychologists are trained to:

- Assess intent, planning, vulnerability, and escalation patterns
- Interpret risk signals dynamically rather than through static thresholds  
- Distinguish between borderline and unsafe cases
- Apply contextual clinical judgment consistent with therapeutic standards
- Interpret individual turns within broader conversational context

This clinical expertise ensures that both conversations and annotations reflect realistic therapeutic scenarios and appropriate safety thresholds.

## Dataset Structure

The dataset is provided in Parquet format with the following schema:

- **`prompt`**: List of conversation turns leading up to the user message
  - `role`: Speaker role (user/assistant)  
  - `content`: Turn content
- **`user_message`**: The specific user turn being evaluated
- **`label`**: Final safety classification (safe/self_harm/harm_others)
- **`annotator_labels`**: Individual annotations from three clinical psychologists
  - `annotator_1`: First psychologist's label
  - `annotator_2`: Second psychologist's label  
  - `annotator_3`: Third psychologist's label

## Clinical Significance

The 96.3% safe / 3.7% unsafe class distribution reflects **clinically meaningful imbalance**—the relative rarity of acute crisis disclosures in mental health conversations while ensuring coverage of high-risk interactions. This distribution is essential for developing safety classifiers that avoid:

1. **False positives** that disrupt therapeutic care and erode patient trust
2. **Over-triggering** on metaphorical expressions, historical references, or normal therapeutic content
3. **Unnecessary escalation** that can perpetuate shame and reduce disclosure willingness

## Usage and Applications

*Keeping in mind the stated limitations*, this dataset enables evaluation of safety classifiers for:
- Turn-level risk classification in multi-turn therapeutic conversations
- Contextual safety assessment that considers conversation history
- Clinical appropriateness of safety interventions in mental health AI
- Comparison with general-purpose safety classifiers
- Development of domain-specific safety measures

## License

This dataset is released under the CC-BY-NC-SA-4.0 license.

## Citation

If you use MindGuard-testset in your research, please cite:

```
@misc{mindguardguard,
      title={MindGuard: Guardrail Classifiers for Multi-Turn Mental Health Support}, 
      author={António Farinhas and Nuno M. Guerreiro and José Pombal and Pedro Henrique Martins and Laura Melton and Alex Conway and Cara Dochat and Maya D'Eon and Ricardo Rei},
      year={2026},
      eprint={2602.00950},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2602.00950}, 
}
```


