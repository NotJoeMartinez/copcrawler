
class GeocodeValidatorResult {
    is_valid bool @description("Whether the geocoded address is valid or not")
}

function NormalGeocodeValidator (
    input_address: string,
    geocoded_address: string
    ) -> GeocodeValidatorResult {
        client "openai/gpt-4o-mini"
        prompt #"
        Your job is to validate the following geocoded address (geocoded_address) by 
        comparing it against the input address (input_address).
       
        Treat the address as a normal address to a building allow for 
        addition of street, city name and state info as well as abbreviations 
        of common address features.

        Allow for directions to be prepended to the address like N, S, E and W 

        - Valid Example:
            - input_address: 1836 Airline
            - geocoded_address:  1836, Airline Drive, Houston, TX
        
        - Invalid Example
            - input_address: 10401 West, Belfort Avenue, and 11599 Belfort Village Drive
            - geocoded_address: Harris County, TX
        
        A strong indication of an invalid geocoded address is if the the geocoded address
        is just the county name and state.

        ---
        {{ ctx.output_format }}

        ---

        {{ _.role("user") }}
        input_address: {{ input_address }}
        geocoded_address: {{ geocoded_address }}

        "#

}

function PlaceGeocodeValidator(input_address: string, geocoded_address: string) -> GeocodeValidatorResult {

    client "openai/gpt-4o-mini"
    prompt #"
        Your job is to validate the following geocoded address (geocoded_address) by 
        comparing it against the input address (input_address).
    
        The input_address should look like a general landmark location using 
        the name of the location in it. the output_address should look like 
        a normal building address

        Allow for directions to be prepended to the address like N, S, E, W 

        - Valid Example:
            - input_address: Lowe's Home Improvement on Broadway, Smith County, Texas 
            - geocoded_address: 5720 S Broadway Ave, Smith County, Texas 
        
        - Invalid Example
            - input_address: Lowe's Home Improvement on Broadway, Smith County, Texas 
            - geocoded_address: Smith County, Texas 
        
        A strong indication of an invalid geocoded address is if the the geocoded address
        is just the county name and state.

        ---
        {{ ctx.output_format }}

        ---

        {{ _.role("user") }}
        input_address: {{ input_address }}
        geocoded_address: {{ geocoded_address }}

        "#
    
}


function IntersectionGeocodeValidator(input_address: string, geocoded_address: string) -> GeocodeValidatorResult {

    client "openai/gpt-4o-mini"
    prompt #"
        Your job is to validate the following geocoded address (geocoded_address) by 
        comparing it against the input address (input_address).

        The input_address should look like an intersection of two streets, usually
        using the word "and" to connect the two streets. the output_address should look
        like two abbreviations of the streets separated by an ampersand. Even
        if one of the streets in the input_address is in the the output_address, it 
        needs to be coupled with the other street in the output_address.

        Allow for directions to be prepended to the address like N, S, E, W 

        - Valid Example:
            - input_address: 23rd Avenue and Southern Avenue
            - geocoded_address: W Southern Ave & S 23rd Ave

        - Invalid Example:
            - input_address: 23rd Avenue and Southern Avenue
            - geocoded_address: 23rd Avenue, Maricopa County, Arizona

        A strong indication of an invalid geocoded address is if the the geocoded address
        is just the county name and state.
            
        ---
        {{ ctx.output_format }}
    
        ---

        {{ _.role("user") }}
        input_address: {{ input_address }}
        geocoded_address: {{ geocoded_address }}

    "#
}

