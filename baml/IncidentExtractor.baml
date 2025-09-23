


class JustificationResult {
    extract_incident bool @description(#"Set to true if and only if the transcript contains actionable and relevant information, 
    that can be classified on a police/fire/ems dashboard"#)
}

function JustifyIncident(
    transcript: string,
) -> JustificationResult {

    client "openai/gpt-4o-mini"
    prompt #"
        {{ _.role("system") }} 
        You are a helpful assistant that determines if a police/fire/ems scanner transcript contains actionable information that 
        can be classified on a police/fire/ems dashboard. You will be given a transcript and your job is to determine if the 
        transcript contains actionable information that can be classified on a police/fire/ems dashboard. We only want 
        incidents with actionable and relevant information.

        What is actionable information?
        - Information that can be used to classify the incident into a set of types of incidents
        - Information that can be used to geo-locate the incident

        What is relevant information?
        - Information that relates to police/fire/ems incidents such that would be worthwhile to plot and publish on a police/fire/ems dashboard
        - Ignore general chit chat or administrative information

        {{ _.role("user") }} 
        Using the transcript, determine if the transcript contains any actionable and relevant information. Ignore general chit chat or 
        other non-actionable information.


        <transcript>
        {{ transcript }}
        </transcript>

        {{ ctx.output_format }}

    "#

}


class ClassificationResult {
    type_of_incident string @description("The type of police/fire/ems incident in less than three words, set to UNKNOWN if it's not clear")
    meta_category MetaCategory @description("The meta category of the incident, if it's not clear, set to UNKNOWN")
    description string @description("A description of the incident, leave blank if it's not clear")
}
function ClassifyIncident(
    transcript: string,
    ) -> ClassificationResult {
        
    client "openai/gpt-4o-mini"
    prompt #"

        {{ _.role("system") }} 
        You will be given a transcript of police/fire/ems scanner audio, your job is to 
        classify the general `type_of_incident` in less than three words, classify the meta_category,
        using the set of meta categories, and give a brief description of the incident. Keep in mind that the transcript
        is not always accurate so keep some wiggle room for the type of incident and meta category. Classify it as UNKNOWN
        if you come to the determination that it is not clear or that the final `type_of_incident` is out of the ordinary 
        for what is normally said on a police/fire/ems scanner.


        {{ _.role("user") }} 
        This is a transcript of police/fire/ems scanner audio, classify the general `type_of_incident` in less than three words, 
        the `meta_category` using the set of meta categories, and give a brief description of the incident.
        Classify it as UNKNOWN if you come to the determination that it is not clear or that the final `type_of_incident` is out of the ordinary
        for what is normally said on a police/fire/ems scanner.


        <transcript>
        {{ transcript }}
        </transcript>
        
        {{ ctx.output_format }}
    "#
}



// incident keyword selector
class IncidentKeywordSelectorResult{
    relevant_keywords string[] @description(#"The keywords that are relevant to the incident, if there are no relevant keywords, return an empty list"#)
}

function IncidentKeywordSelector(
    transcript: string,
    valid_keywords: string @description("A string of valid keywords separated by commas")
) -> IncidentKeywordSelectorResult {
    client "openai/gpt-4o-mini"
    prompt #"
        {{ _.role("system") }} 
        You are a helpful assistant that determines if a police/fire/ems scanner transcript contains relevant keywords.
        You will be given a transcript and a list of `valid_keywords`. Your job is to select the `valid_keywords` that are semantically 
        relevant to the transcript. You're not looking for exact matches although that counts, you're looking for semantically 
        relevant keywords. If there are no relevant keywords, return an empty list. Don't hallucinate keywords that are not in the `valid_keywords` list.


        {{ _.role("user") }} 
        This is a transcript of police/fire/ems scanner audio, select the `valid_keywords` that are semantically relevant to the transcript and return them in a list `relevant_keywords`. If there are no relevant keywords, return an empty list.

        <valid_keywords>
        {{ valid_keywords }}
        </valid_keywords>

        <transcript>
        {{ transcript }}
        </transcript>

        {{ ctx.output_format }}
    "#
}






class GeocodeableAddressResult {
  has_address bool @description("Whether the transcript contains a valid address that can be geocoded")
}
function CheckForGeocodeableAddress(transcript: string) -> GeocodeableAddressResult {
  client "openai/gpt-4o-mini"
  prompt #"

    {{ _.role("system") }} 
    You will be given a transcript of police/fire/ems scanner audio and your job is to determine if the transcript contains a valid address that can be geocoded.


    {{ _.role("user") }}
    This is a transcript of police/fire/ems scanner audio, determine if the transcript contains a valid address that can be geocoded.

    <transcript>
    {{ transcript }}
    </transcript>

    {{ ctx.output_format }}
  "#
}


class IncidentLocationResult {
    extracted_location string @description(#"The possible location in the text, usually a street address or intersection"#)
    address_type AddressType @description("The type of address extracted from the text")
    confidence_score int @description("How confident you are of the location given the context, on a scale of 1 to 5, 1 being there is no given location in the context")
}

function ExtractIncidentLocation(
    transcript: string
    ) -> IncidentLocationResult {

    client "openai/gpt-4o-mini"
    prompt #"

        {{ _.role("system") }} You will be given a transcript of police/fire/ems scanner audio and
        a relative location where the audio was taken from. Your job is to extract the possible location
        from the transcript text, classify the type of address and give a score of how confident you are
        of the location given the context.


        {{ _.role("user") }} 
        This is a transcript of police/fire/ems scanner audio, extract the possible location
        from the text, classify the type of address and give a score of how confident you are of 
        the location given the context.

        <transcript>
        {{ transcript }}
        </transcript>

        {{ ctx.output_format }}
    "#
}


class ValidateClassificationLocationResult {
    is_valid bool @description("Whether the transmission_text matches the extracted_location and type_of_incident")
}


function ValidateIncidentClassificationLocation(
    transmission_text: string @description("The transcript of a police/fire/ems scanner audio"),
    type_of_incident: string @description("The type of incident it was classified as from a previous LLM"),
    extracted_location: string @description("The location extracted from the transcript from a previous LLM")
) ->  ValidateClassificationLocationResult {
    client "openai/gpt-4o"
    prompt #"
        {{ _.role("system") }} 
        You are an accurate incident validator that determines if a police/fire/ems scanner audio is a valid incident.
        You will be given the transcript of a police/fire/ems scanner audio, the type of incident it was classified as
        from a previous LLM and the location extracted from the text from a previous LLM. Your job is to determine if 
        the text of the incident matches the type of incident and the location extracted from the text matches the location 
        extracted from the text from a previous LLM.

        An incident is valid if the text of the incident matches the semantic type of incident and the location closely 
        matches the location text extracted from the text from a previous LLM. Keep in mind that the transcript
        is not always accurate so keep some wiggle room for the location.

        {{ ctx.output_format }}

        ---
        {{ _.role("user") }} Please determine if the transmission text is a valid incident.

        Criteria for a valid incident:
        1. The text of the incident matches the type of incident semantically
        2. The location extracted from the text matches the location extracted from the text from a previous LLM

        <type_of_incident>
        {{ type_of_incident }}
        </type_of_incident>

        <extracted_location>
        {{ extracted_location }}
        </extracted_location>

        <transmission_text>
        {{ transmission_text }}
        </transmission_text>
    "#
}