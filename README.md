# Description

`chisel` - a tool for testing and benchmarking the Tensorflight app.

The script sends requests to `/api/request_processing_location`, 
and then queries `/api/get_features` in configurable intervals for a specified number of tries, 
or until it receives the results. 

To use the script, the user should possess an API key, 
as well as a file with addresses (one per line). 

### Example usage

To run 100 requests at random from file, spaced as 10 requests per second:
```commandline
python chisel.py --limit 100 --stagger 0.1 --shuffle https://app.tensorflight.com API_KEY ADDRESSES_FILE
```

For information about available parameters and their description, as well as for more usage examples, please run:
```commandline
python chisel.py --help
```