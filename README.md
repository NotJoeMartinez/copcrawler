# [copcrawler.com](https://copcrawler.com/)

Some code snippets of the audio preprocessing, transcription, incident classification, and 
geocoding workflow for copcrawler.com. 


## LLM classification & geocoding 

```mermaid
flowchart TD
    A[Start: Radio Transmission] --> B[Split by Talkgroups]
    B --> C[For each transmission]
    C --> D{No Speech Found?}
    D -->|Yes| C
    D -->|No| E{Duplicate text?}
    E -->|Yes| C
    E -->|No| F[**JustifyIncident**<br/>LLM Function]
    
    F --> G{Extract incident?}
    G -->|No| H[Skip transmission]
    G -->|Yes| I[**ClassifyIncident**<br/>LLM Function]
    
    I --> J{Classification valid?}
    J -->|No - UNKNOWN| H
    J -->|Yes| K[**CheckForGeocodeableAddress**<br/>LLM Function]
    
    K --> L{Has address?}
    L -->|No| H
    L -->|Yes| M[**ExtractIncidentLocation**<br/>LLM Function]
    
    M --> N{Location extracted?}
    N -->|No| H
    N -->|Yes| O[**ValidateIncidentClassificationLocation**<br/>LLM Function]
    
    O --> P{Validation passed?}
    P -->|No| H
    P -->|Yes| Q[**IncidentKeywordSelector**<br/>LLM Function]
    
    Q --> R[Create LLM Transcript Node]
    R --> S[**Geocoding Process**]
    
    S --> T[Check Cache]
    T --> U{Cached result?}
    U -->|Yes| V[Use cached coordinates]
    U -->|No| W[LocationIQ Geocoding]
    
    W --> X{Geocoding successful?}
    X -->|No| Y[Skip incident]
    X -->|Yes| Z[**Validate Geocode**<br/>Based on address type]
    
    Z --> AA[**NormalGeocodeValidator**<br/>**PlaceGeocodeValidator**<br/>**IntersectionGeocodeValidator**<br/>LLM Functions]
    AA --> BB{Geocode valid?}
    BB -->|No| Y
    BB -->|Yes| CC[Cache result]
    CC --> DD[Create Simplified Incident]
    
    V --> DD
    DD --> EE[Return processed incidents]
    
    H --> C
    Y --> C
    
    %% style F fill:#e1f5fe
    %% style I fill:#e1f5fe
    %% style K fill:#e1f5fe
    %% style M fill:#e1f5fe
    %% style O fill:#e1f5fe
    %% style Q fill:#e1f5fe
    %% style AA fill:#e1f5fe
    
    classDef llmFunction fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    classDef decision fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef process fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef endpoint fill:#e8f5e8,stroke:#1b5e20,stroke-width:2px
```

## LLM Functions Overview

### 1. **JustifyIncident** (`gpt-4o-mini`)
- **Input**: Transcript text
- **Output**: `extract_incident` (boolean)
- **Purpose**: Determines if transcript contains actionable police/fire/ems information

### 2. **ClassifyIncident** (`gpt-4o-mini`)  
- **Input**: Transcript text
- **Output**: `type_of_incident`, `meta_category`, `description`
- **Purpose**: Classifies incident type and meta-category

### 3. **CheckForGeocodeableAddress** (`gpt-4o-mini`)
- **Input**: Transcript text  
- **Output**: `has_address` (boolean)
- **Purpose**: Determines if transcript contains a geocodeable address

### 4. **ExtractIncidentLocation** (`gpt-4o-mini`)
- **Input**: Transcript text
- **Output**: `extracted_location`, `address_type`, `confidence_score`
- **Purpose**: Extracts location information and classifies address type

### 5. **ValidateIncidentClassificationLocation** (`gpt-4o`)
- **Input**: Transmission text, type of incident, extracted location
- **Output**: `is_valid` (boolean)
- **Purpose**: Cross-validates that extracted location matches incident classification

### 6. **IncidentKeywordSelector** (`gpt-4o-mini`)
- **Input**: Transcript text, valid keywords list
- **Output**: `relevant_keywords` (array)
- **Purpose**: Selects semantically relevant keywords from predefined list

### 7. **Geocode Validators** (`gpt-4o-mini`)
- **NormalGeocodeValidator**: Validates standard address geocoding
- **PlaceGeocodeValidator**: Validates place/landmark geocoding  
- **IntersectionGeocodeValidator**: Validates intersection geocoding
- **Input**: LLM extracted address, geocoded address
- **Output**: `is_valid` (boolean)
- **Purpose**: Ensures geocoding service results match LLM extracted addresses

## Workflow Summary

The system processes radio transmissions through a multi-stage LLM pipeline:

1. **Pre-processing**: Split transmissions by talkgroups, filter duplicates/empty
2. **Justification**: Determine if transmission is actionable
3. **Classification**: Categorize incident type and severity
4. **Address Detection**: Check for geocodeable addresses
5. **Location Extraction**: Extract specific location details
6. **Cross-validation**: Verify location matches classification
7. **Keyword Selection**: Extract relevant trigger keywords
8. **Geocoding**: Convert addresses to coordinates with validation
9. **Output**: Generate simplified incident records for dashboard display

The pipeline uses 7 different LLM functions with robust validation and caching to ensure high-quality incident data extraction from scanner audio transcripts.