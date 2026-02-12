import random
rand_list = [random.randint(1, 20) for _ in range(10)]

list_comprehension_below_10 = [number for number in rand_list if number < 10]

list_comprehension_below_10 = filter(rand_list)