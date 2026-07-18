
# How to handle Problematic Tables, Codeblock and Pictures

- One of the difficulty in getting a good quality PDF from other ebook formats is
  that tables, code blocks (and some times pictures) loose their formatting and lays out poorly in the out put!
- A work around will be providing manual assist to the conversion pipeline
- The idea is to specify an auxilary optional YAML input file that specifies 
  the regions to be overridden, i.e. poorly laid out table, code block etc.
- The conversion pipeline can the do a fuzzy search in the intermediate epub file
  and replace the block with the input specified in the YAML file.
- The YAMML file can, for each block to be replaced, have a multiline UTF8 data 
  specifying the inputs and outputs (i.e. the prologue and epilogue of the block, and  
  replacement).
- The replacement block shall be expressed in Markdown format with support for code 
  blocks with syntax higlight capability, tables and SVG/PNG/JPEG pictures.
- Suggested YAML Format :

```yaml

filename : <Base name of the file being converted>
    block :
        type : <table/code-block/figure>
        prologue: |
        djfhshgsghje 
        sdjkgkjgjl
        sglklsfglll
        ....
        <text just before the block being overridden>

        epilogue: |
        <text immediately trailing the block>

        replacement: |
        <Markdown text representing the desired content>
```

- The convertor need to do a fuzzy search for locating the block in the intermediate
  epub, as exact match will be very user unfriendly.

