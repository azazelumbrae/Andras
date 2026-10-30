require_relative '../inflector.rb'
require_relative '../tld.rb'
require_relative '../common-misspellings.rb'
require_relative '../homophones.rb'
require_relative '../country.rb'
require_relative 'typo.rb'

require_relative 'keyboard'

class Domainname
  attr_accessor :domain, :registered_name, :tld, :extension, :valid, :typos, :keyboard
  
  def initialize(d, keyboard_layout='qwerty')
    @typos = []
    @domain = d
    @extension = TLD.extension(d)
    @valid = TLD.valid_domain?(d)
    @registered_name = TLD.registered_name(d) if @valid
    @keyboard = Keyboard.new(keyboard_layout)
  end
  
  def create_typos
    # Save the original domain for comparison
    original_domain = @domain
    
    # Add original domain first
    self.original.sort.uniq.each { |c|
        t = Typo.new
        t.type = "Original"
        t.name = c
        t.valid_name = TLD.valid_domain?(c)
        @typos << t
    }

    # Helper method to add typos only if they don't match the original domain
    def add_typo(typo_type, domain)
      if domain != @domain
        t = Typo.new
        t.type = typo_type
        t.name = domain
        t.valid_name = TLD.valid_domain?(domain)
        @typos << t
      end
    end

    self.character_omission.sort.uniq.each { |c|
        add_typo("Character Omission", c)
    }

    self.character_repeat.sort.uniq.each { |c|
        add_typo("Character Repeat", c)
    }
    
    self.character_swap.sort.uniq.each { |c|
        add_typo("Character Swap", c)
    }
    self.character_replacement.sort.uniq.each { |c|
        add_typo("Character Replacement", c)
    }
    self.double_character_replacement.sort.uniq.each { |c|
        add_typo("Double Replacement", c)
    }
    self.character_insertion.sort.uniq.each { |c|
        add_typo("Character Insertion", c)
    }

    self.missingdot.sort.uniq.each { |c|
        add_typo("Missing Dot", c)
    }
=begin
    self.insert_dot.sort.uniq.each { |c|
        t=Typo.new
        t.type = "Insert Dot"
        t.name = c
        t.valid_name = TLD.valid_domain?(c)
        @typos << t
    }
=end
    self.insert_dash.sort.uniq.each { |c|
        add_typo("Insert Dash", c)
    }

    self.stripdashes.sort.uniq.each { |c|
        add_typo("Strip Dashes", c)
    }

    self.singular_or_pluralise.sort.uniq.each { |c|
        add_typo("Singular or Pluralise", c)
    } 

    self.common_misspellings.sort.uniq.each { |c|
        add_typo("Common Misspelling", c)
    } 

    self.vowel_swap.sort.uniq.each { |c|
        add_typo("Vowel Swap", c)
    } 

    self.homophones.sort.uniq.each { |c|
        add_typo("Homophones", c)
    } 

    self.bit_flipping.sort.uniq.each { |c|
        add_typo("Bit Flipping", c)
    } 

    self.homoglyphs.sort.uniq.each { |c|
      add_typo("Homoglyphs", c)
    }

    self.wrong_tld.sort.uniq.each { |c|
      add_typo("Wrong TLD", c)
    } 

    self.wrong_sld.sort.uniq.each { |c|
      add_typo("Wrong SLD", c)
    } 
#=begin
    self.all_sld.sort.uniq.each { |c|
      add_typo("All SLD", c)
    }

    self.domain_prefix.sort.uniq.each { |c|
      add_typo("Domain Prefix", c)
    }
    
    self.domain_suffix.sort.uniq.each { |c|
      add_typo("Domain Suffix", c)
    }
#=end
  end

  def original
    return [@domain]
  end

  def character_omission
    a = Array.new
    0.upto(@registered_name.length-1) { |n|
      a << @registered_name[0,n] + @registered_name[n+1..-1] + "." + @extension
    }
    return a
  end

  def character_repeat
    a = Array.new
    0.upto(@registered_name.length-1) { |n|
      a << @registered_name[0,n] + @registered_name[n,1] + @registered_name[n,1] + @registered_name[n+1..-1] + "." + @extension
    }
    return a
  end

  def character_swap
    a = Array.new
    0.upto(@registered_name.length-2) { |n|
      a << @registered_name[0,n] + @registered_name[n+1,1] + @registered_name[n,1] + @registered_name[n+2..-1] + "." + @extension
    }
    return a
  end

  def character_replacement
    a = Array.new
    k = @keyboard
    0.upto(@registered_name.length-1) { |n|
      char = @registered_name[n,1]
      left = k.key_left(char)
      right = k.key_right(char)
      a << @registered_name[0,n] + left + @registered_name[n+1..-1] + "." + @extension if !left.nil?
      a << @registered_name[0,n] + right + @registered_name[n+1..-1] + "." + @extension if !right.nil?
    }
    return a
  end

  def double_character_replacement
    a = Array.new
    k = @keyboard
    0.upto(@registered_name.length-1) { |n|
      char = @registered_name[n,1]
      left = k.key_left(char)
      right = k.key_right(char)
      a << @registered_name[0,n] + left + left + @registered_name[n+1..-1] + "." + @extension if !left.nil?
      a << @registered_name[0,n] + right + right + @registered_name[n+1..-1] + "." + @extension if !right.nil?
    }
    return a
  end

  def character_insertion
    a = Array.new
    k = @keyboard
    0.upto(@registered_name.length-1) { |n|
      char = @registered_name[n,1]
      left = k.key_left(char)
      right = k.key_right(char)
      a << @registered_name[0,n] + left + @registered_name[n..-1] + "." + @extension if !left.nil?
      a << @registered_name[0,n] + right + @registered_name[n..-1] + "." + @extension if !right.nil?
    }
    return a
  end

  def missingdot
    a = Array.new
    if @registered_name.include?(".")
      a << @registered_name.delete(".") + @extension
    end
    return a
  end

  def insert_dot
    a = Array.new
    1.upto(@registered_name.length-1) { |n|
      a << @registered_name[0,n] + "." + @registered_name[n..-1] + "." + @extension
    }
    return a
  end

  def insert_dash
    a = Array.new
    1.upto(@registered_name.length-1) { |n|
      a << @registered_name[0,n] + "-" + @registered_name[n..-1] + "." + @extension
    }
    return a
  end

  def stripdashes
    a = Array.new
    if @registered_name.include?("-")
      a << @registered_name.delete("-") + "." + @extension
    end
    return a
  end

  def singular_or_pluralise
    a = Array.new
    a << ActiveSupport::Inflector.singularize(@registered_name) + "." + @extension
    a << ActiveSupport::Inflector.pluralize(@registered_name) + "." + @extension
    return a
  end

  def common_misspellings
    CommonMisspellings.dictionary.keys.select { |x| @registered_name.include?(x) }.map { |word|
        @registered_name.gsub(word, CommonMisspellings.misspelling(word)) + "." + @extension
    }
  end

  def vowel_swap
    a = Array.new
    vowels = "aeiou"
    0.upto(@registered_name.length-1) { |n|
      char = @registered_name[n,1]
      if vowels.include?(char)
        vowels.each_byte { |v|
          a << @registered_name[0,n] + v.chr + @registered_name[n+1..-1] + "." + @extension
        }
      end
    }
    return a
  end

  def homophones
    Homophones.dictionary.keys.select { |x| @registered_name.include?(x) }.map { |word|
        Homophones.dictionary[word].map { |homophoneword| @registered_name.gsub(word,homophoneword) + @extension } }.flatten
  end

  def bit_flipping
    a = Array.new
    0.upto(@registered_name.length-1) { |n|
      original_char = @registered_name[n,1]
      original_char_ascii = original_char.unpack('c')[0]
      (0..7).each { |m|
        flipped_char_ascii = original_char_ascii ^ (2**m)
        if (flipped_char_ascii >= 97 && flipped_char_ascii <= 122) || (flipped_char_ascii >= 48 && flipped_char_ascii <= 57) || flipped_char_ascii == 45
          flipped_char = flipped_char_ascii.chr
          a << @registered_name[0,n] + flipped_char + @registered_name[n+1..-1] + "." + @extension
        end
      }
    }
    return a
  end

  def replace_permutations(string, pattern, replacement)
    permutations=[]
      # how many times does pattern appear? it is n
      n = string.scan(pattern).size
      # generate perumations map for n times
      map = [pattern,replacement].repeated_permutation(n).map

      # for each occurance of pattern, replace using the map
      map.each do |mapset|
          strsplit = string.split(pattern)
          mapset.each_with_index do |thisreplacement, i|
              strsplit[i] = strsplit[i] + thisreplacement
          end
          permutations << strsplit.join
      end
      permutations.flatten.sort.uniq - [string]
  end

  def homoglyphs
    #https://en.wikipedia.org/wiki/Homoglyph
    homoglyphs = {"0"=>"o", "1"=>"l", "l"=> "i", "rn" => "m", "cl"=>"d", "vv"=>"w" }
    all_homoglyphs = homoglyphs.merge(homoglyphs.invert)
    list=[]
    all_homoglyphs.each_pair { |x, y|
        list << replace_permutations(@registered_name,x,y)
    }
    list.flatten.sort.uniq.map { |d| d + "." + @extension }
  end

  def wrong_tld
    TLD.all_tlds.map { |tld| @registered_name + "." + tld }
  end

  def wrong_sld
    if TLD.valid_sld?(@domain)
        TLD.cc(TLD.tld(@domain))['slds'].map { |x| @registered_name + "." + x }
    else
        []
    end
  end

  def all_sld
    all_slds = TLD.hash.map {|tld,hash| hash["slds"] unless hash["slds"].empty? }.compact.flatten
    all_slds.map {|sld| "#{@registered_name}.#{sld}" }
  end

  def domain_prefix
    a = Array.new
    prefix_file = File.join(File.dirname(__FILE__), '..', 'prefix-dictionary.txt')
    
    if File.exist?(prefix_file)
      File.readlines(prefix_file).each do |line|
        line.strip!
        next if line.empty? || line.start_with?('#')
        a << "#{line}-#{@registered_name}.#{@extension}"
      end
    end
    return a
  end
  
  def domain_suffix
    a = Array.new
    suffix_file = File.join(File.dirname(__FILE__), '..', 'suffix-dictionary.txt')
    
    if File.exist?(suffix_file)
      File.readlines(suffix_file).each do |line|
        line.strip!
        next if line.empty? || line.start_with?('#')
        a << "#{@registered_name}-#{line}.#{@extension}"
      end
    end
    return a
  end

end
